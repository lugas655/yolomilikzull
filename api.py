import os
import cv2
import numpy as np
import base64
import re
import mysql.connector
from flask import Flask, request, jsonify, render_template
from ultralytics import YOLO
from flask_cors import CORS

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
CORS(app)

# --- KONFIGURASI ---
MODEL_YOLO_PATH = os.environ.get('MODEL_YOLO_PATH', 'bestmodel.pt')

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'slimsumpo')
}

PORT = int(os.environ.get('PORT', 5005))

# Buffer untuk Sinkronisasi
signal_buffer = None
receipt_buffer = None

# FIX: Deklarasi global dulu agar tidak "not defined" jika load gagal
model_yolo = None

# --- LOAD MODELS ---
print("Memuat model YOLO...")
try:
    model_yolo = YOLO(MODEL_YOLO_PATH)
    print("  [OK] YOLO berhasil dimuat.")
except Exception as e:
    print(f"  [GAGAL] YOLO: {e}")

# Pemuatan model FaceNet, SVM, dan Label Encoder dihapus


def get_member_info(nim):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT member_name, inst_name FROM member WHERE member_id = %s", (nim,))
        data = cursor.fetchone()
        cursor.close()
        conn.close()
        return data
    except Exception as e:
        print(f"Database error: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scan_face', methods=['POST'])
def scan_face():
    global signal_buffer

    # FIX: Cek apakah model sudah ter-load sebelum digunakan
    if model_yolo is None:
        return jsonify({
            "status": "error",
            "message": "Model YOLO belum ter-load. Cek log server untuk detail error."
        })

    try:
        data = request.json
        img_b64 = data.get('image')
        img_data = re.sub('^data:image/.+;base64,', '', img_b64)
        np_arr = np.frombuffer(base64.b64decode(img_data), np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        # --- ENHANCEMENT UNTUK KONDISI GELAP (LOW-LIGHT) ---
        # Menggunakan CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # Pisahkan channel kecerahan (Luminance) dari warna agar warna tidak rusak
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Terapkan CLAHE untuk menerangkan area yang gelap secara otomatis
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
        cl = clahe.apply(l)
        
        # Gabungkan kembali dan kembalikan ke format BGR
        limg = cv2.merge((cl, a, b))
        frame = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        # ---------------------------------------------------

        # STEP 1: Deteksi lokasi & klasifikasi wajah dengan YOLO
        results = model_yolo.predict(source=frame, conf=0.4, verbose=False)
        
        if len(results) > 0 and len(results[0].boxes) > 0:
            # Ambil deteksi dengan confidence tertinggi (box pertama)
            box_data = results[0].boxes[0]
            box = box_data.xyxy.cpu().numpy()[0] # [x1, y1, x2, y2]
            conf = float(box_data.conf.cpu().numpy()[0])
            class_idx = int(box_data.cls.cpu().numpy()[0])
            
            x1, y1, x2, y2 = map(int, box)
            
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            
            # Dapatkan NIM langsung dari nama kelas YOLO
            if class_idx in model_yolo.names:
                nim = str(model_yolo.names[class_idx])
            else:
                nim = str(class_idx)
            
            # STEP 2: Ambil data dari MySQL
            member = get_member_info(nim)
            if member:
                signal_buffer = nim
                
                # --- GAMBAR KOTAK HIJAU SAJA ---
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 4) # Kotak Hijau tebal 4
                
                # Kompresi gambar JPEG dengan kualitas 60% agar hemat bandwidth dan cepat terunduh via Ngrok
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                
                return jsonify({
                    "status": "success",
                    "nim": nim,
                    "member_name": member['member_name'],
                    "inst_name": member['inst_name'],
                    "confidence": round(conf * 100, 1),
                    "result_image": frame_b64
                })
        
        return jsonify({"status": "failure", "message": "Wajah tidak terdaftar atau kemiripan rendah"})
    
    except Exception as e:
        print(f"Error pada /scan_face: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/get_signal', methods=['GET'])
def get_signal():
    global signal_buffer
    if signal_buffer:
        nim = signal_buffer
        signal_buffer = None
        return jsonify({"status": "ok", "nim": nim})
    return jsonify({"status": "empty"})

@app.route('/send_receipt', methods=['POST'])
def send_receipt():
    global receipt_buffer
    data = request.json
    receipt_buffer = data
    return jsonify({"status": "ok"})

@app.route('/get_receipt', methods=['GET'])
def get_receipt():
    # Baca struk langsung dari database SLiMS!
    nim = request.args.get('nim')
    since = request.args.get('since')
    
    if not nim or not since:
        return jsonify({"status": "empty"})
        
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        # Mengambil transaksi peminjaman (loan) terbaru sejak waktu scan (since)
        query = """
        SELECT b.title as buku, l.loan_date as tgl_pinjam, l.due_date as tgl_kembali 
        FROM loan l
        JOIN item i ON l.item_code = i.item_code
        JOIN biblio b ON i.biblio_id = b.biblio_id
        WHERE l.member_id = %s AND l.input_date >= %s
        ORDER BY l.input_date DESC LIMIT 1
        """
        cursor.execute(query, (nim, since))
        receipt = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if receipt:
            # Ubah tipe date menjadi string agar bisa dikirim sebagai JSON
            receipt['tgl_pinjam'] = str(receipt['tgl_pinjam'])
            receipt['tgl_kembali'] = str(receipt['tgl_kembali'])
            return jsonify({"status": "found", "data": receipt})
            
    except Exception as e:
        print(f"Error membaca struk dari DB: {e}")
        
    return jsonify({"status": "empty"})

if __name__ == '__main__':
    print("\n" + "="*50)
    print(f"SISTEM ABSENSI PERPUSTAKAAN (YOLO DIRECT)")
    print(f"Sistem berjalan di http://0.0.0.0:{PORT}")
    print("="*50 + "\n")

    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\nMematikan Server...")