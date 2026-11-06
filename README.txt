# SURAT JALAN → PESANAN (Streamlit)

Aplikasi ini dibuat berdasarkan dua contoh PDF yang diberikan.

## Prinsip data
1. PDF Surat Jalan: dibaca hanya kolom SKU dan QTY. Kolom NAMA BARANG pada Surat Jalan tidak dipakai.
2. PDF database harga: SKU/Barcode menjadi kunci pencarian; nama produk dan HET Offline diambil dari master.
3. SKU disimpan sebagai teks agar digit barcode tetap persis.
4. Tim area menentukan persentase diskon untuk setiap SKU.
5. Persentase diskon ditampilkan di kolom DISKON PDF akhir (contoh 30,00%).
6. Sistem hanya menghitung nominal diskon, harga setelah diskon, dan grand total.

## File dalam project
- app.py
- requirements.txt
- Data Harga - Google Spreadsheet.pdf
- logo_oxar.jpg
- .streamlit/config.toml
- .gitignore

## A. Menjalankan di Windows secara lokal
1. Install Python dari https://www.python.org/downloads/
2. Ekstrak ZIP project.
3. Buka folder project di Visual Studio Code.
4. Buka Terminal > New Terminal.
5. Jalankan:
   ```bash
   python -m venv venv
   ```
6. Aktifkan:
   ```bash
   venv\Scripts\activate
   ```
7. Install library:
   ```bash
   pip install -r requirements.txt
   ```
8. Jalankan:
   ```bash
   streamlit run app.py
   ```
9. Browser membuka http://localhost:8501

## B. Upload ke GitHub
1. Buat akun/login di https://github.com
2. Klik New repository.
3. Nama repository: surat-jalan-pesanan
4. Pilih Private (disarankan karena PDF master memuat daftar harga).
5. Buat repository.
6. Upload seluruh isi folder project, termasuk file PDF master dan logo.
7. Jangan upload folder `venv`.
8. Jangan upload file `.streamlit/secrets.toml`.

## C. Deploy ke Streamlit Community Cloud
1. Buka https://share.streamlit.io
2. Login menggunakan GitHub.
3. Klik Create app.
4. Pilih repository `surat-jalan-pesanan`.
5. Branch: `main`.
6. Main file path: `app.py`.
7. Advanced settings: pilih Python versi 3.12 atau versi yang didukung.
8. Klik Deploy.

Streamlit Community Cloud akan membaca requirements.txt dan menginstal library secara otomatis.

## D. Mengatur akses aplikasi
- Jika aplikasi harus dipakai tim melalui satu link tanpa undangan satu per satu, atur Sharing aplikasi menjadi Public.
- Repository GitHub tetap Private. Jangan mengubah repository menjadi Public karena memuat PDF daftar harga.
- Jika ingin meminta password tambahan, masukkan secret di Streamlit Cloud:
  ```toml
  APP_PASSWORD = "GANTI_DENGAN_PASSWORD_KUAT"
  ```
- Jika APP_PASSWORD tidak disetel, aplikasi tidak meminta password.
- Untuk pembatasan akses berbasis email, atur aplikasi sebagai Private dan undang email tim sebagai viewers melalui Streamlit Community Cloud. Ketersediaan fitur private app mengikuti batasan akun/workspace Streamlit.

## E. Memperbarui harga
Ganti file `Data Harga - Google Spreadsheet.pdf` dengan versi terbaru melalui GitHub (tetap gunakan nama file yang sama). Setelah commit, Streamlit Community Cloud akan menjalankan ulang aplikasi.

## Catatan pengujian
- Parser SKU/QTY disesuaikan dengan posisi kolom pada PDF Surat Jalan contoh.
- PDF hasil dibuat ulang dengan urutan dan susunan utama PDF PESANAN contoh, termasuk logo, header, tabel, ringkasan, catatan, tanda tangan, dan tanggal cetak. Ini bukan salinan piksel-per-piksel PDF sumber.
- Uji beberapa PDF Surat Jalan dengan format asli yang berbeda sebelum digunakan untuk transaksi operasional.
- File scan/foto PDF yang tidak memiliki lapisan teks belum didukung oleh parser ini.


## Uji awal pada file contoh
Parser diuji pada PDF Surat Jalan contoh yang diberikan:
- SKU 8994461400238 terbaca dengan QTY 3.
- SKU 8994461400061 terbaca dengan QTY 3.
- Nama barang pada Surat Jalan tidak digunakan.
- Contoh PDF PESANAN berhasil dibuat satu halaman dan menampilkan diskon 30,00% pada kolom DISKON.

Hasil uji ini hanya berlaku untuk format PDF contoh tersebut. Sebelum operasional, lakukan uji pada variasi dokumen Surat Jalan yang akan dipakai tim area.
