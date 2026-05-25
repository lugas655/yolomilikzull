// ==UserScript==
// @name         SLiMS Face Recognition Auto-Fill (Port 5002)
// @namespace    http://tampermonkey.net/
// @version      1.2
// @description  Mengambil NIM dari sistem Face Recognition dan mengisi otomatis di SLiMS Circulation
// @author       Anda
// @match        http://perpustakaan.test/admin/index.php?mod=circulation*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    const API_URL = 'http://localhost:5002/get_signal';
    const POLLING_INTERVAL = 2000;

    console.log("[FaceRec] Script Auto-Fill SLiMS berjalan...");

    function checkSignal() {
        if (window.location.search.includes('mod=circulation')) {
            fetch(API_URL)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'ok' && data.nim) {
                        console.log("[FaceRec] NIM Terdeteksi:", data.nim);
                        
                        let memberInput = document.getElementById('memberID') || document.querySelector('input[name="memberID"]');
                        
                        if (memberInput) {
                            memberInput.value = data.nim;
                            
                            // SLiMS mendeteksi input menggunakan AJAX (tombol Enter di keyboard), 
                            // jadi kita simulasikan pengguna menekan tombol Enter pada input tersebut.
                            let enterEvent = new KeyboardEvent('keypress', {
                                key: 'Enter', code: 'Enter', which: 13, keyCode: 13, bubbles: true
                            });
                            memberInput.dispatchEvent(enterEvent);
                            
                            // Untuk jaga-jaga SLiMS mendeteksi keydown/keyup
                            memberInput.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 13, bubbles: true}));
                            memberInput.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', keyCode: 13, bubbles: true}));
                            
                            // Tekan tombolnya secara langsung jika event Enter tidak mempan
                            let form = memberInput.closest('form');
                            if (form) {
                                let submitBtn = form.querySelector('input[value="Start Transaction"], button[type="submit"]');
                                if (submitBtn) {
                                    submitBtn.click();
                                }
                            }
                        }
                    }
                })
                .catch(err => {});
        }
    }

    setInterval(checkSignal, POLLING_INTERVAL);
})();
