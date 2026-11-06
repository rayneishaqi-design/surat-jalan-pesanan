import re
from io import BytesIO
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import pdfplumber
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, KeepTogether
)

# ============================================================
# KONFIGURASI
# ============================================================
st.set_page_config(
    page_title="Surat Jalan → Pesanan",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

BASE_DIR = Path(__file__).resolve().parent
MASTER_PDF = BASE_DIR / "Data Harga - Google Spreadsheet.pdf"
LOGO_FILE = BASE_DIR / "logo_oxar.jpg"


# ============================================================
# LOGIN OPSIONAL
# Jika APP_PASSWORD diisi di Streamlit Secrets, aplikasi meminta
# password. Jika belum diisi, aplikasi berjalan tanpa login.
# ============================================================
def check_password():
    try:
        app_password = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        app_password = ""

    if not app_password:
        return True

    if st.session_state.get("authenticated", False):
        return True

    st.markdown(
        """
        <div class="hero">
          <div class="eyebrow">OXAR GLOBAL • AREA ORDER SYSTEM</div>
          <h1>Masuk ke Sistem Pesanan</h1>
          <p>Gunakan password akses yang diberikan oleh administrator.</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    with st.form("login_form"):
        password = st.text_input("Password akses", type="password")
        submitted = st.form_submit_button("Masuk", use_container_width=True)
    if submitted:
        if password == app_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Password tidak sesuai. Silakan coba lagi.")
    return False


# ============================================================
# CSS / DESAIN APLIKASI
# ============================================================
st.markdown(
    """
    <style>
    .stApp { background: #f5f7fb; }
    .block-container { max-width: 1180px; padding-top: 1.6rem; padding-bottom: 3rem; }
    .hero {
        background: linear-gradient(120deg, #12243a 0%, #1d4260 55%, #287a78 100%);
        padding: 28px 32px; border-radius: 18px; color: white; margin-bottom: 20px;
        box-shadow: 0 10px 28px rgba(17, 36, 58, .12);
    }
    .hero h1 { color: white; font-size: 30px; margin: 5px 0 8px 0; }
    .hero p { color: #e3edf4; margin: 0; font-size: 14px; }
    .eyebrow { color: #b9d8dd; font-size: 11px; letter-spacing: 2px; font-weight: 700; }
    .step-card {
        background: white; border: 1px solid #e6eaf0; padding: 15px 17px;
        border-radius: 13px; min-height: 100px;
    }
    .step-num { color: #16817c; font-weight: 800; font-size: 12px; letter-spacing: 1px; }
    .step-title { color: #172b42; font-size: 15px; font-weight: 700; margin-top: 5px; }
    .step-desc { color: #687789; font-size: 12px; margin-top: 4px; }
    div[data-testid="stMetric"] {
        background: white; border: 1px solid #e7ebf1; padding: 13px 15px;
        border-radius: 13px;
    }
    div[data-testid="stMetricLabel"] { color: #667789; }
    div[data-testid="stMetricValue"] { color: #152d43; font-size: 24px; }
    .note-box {
        background: #edf6f5; border-left: 4px solid #23877e; padding: 12px 15px;
        border-radius: 8px; color: #244b50; font-size: 13px;
    }
    .section-heading { color: #172b42; font-size: 19px; font-weight: 750; margin: 8px 0 10px 0; }
    footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# FUNGSI FORMAT
# ============================================================
def digits_only(value):
    return re.sub(r"[^0-9]", "", str(value))


def parse_master_price(value):
    # Kolom HET Offline pada master umumnya berbentuk 159.000.
    # Titik adalah pemisah ribuan, bukan desimal.
    digits = digits_only(value)
    return int(digits) if digits else 0


def rupiah(value):
    return "Rp" + f"{int(round(float(value))):,}".replace(",", ".")


def number_id(value):
    return f"{int(round(float(value))):,}".replace(",", ".")


def summary_id(value):
    return f"{int(round(float(value))):,}".replace(",", ".") + ",00"


def percent_id(value):
    return f"{float(value):.2f}".replace(".", ",") + "%"


# ============================================================
# DATABASE MASTER
# SKU BARCODE DIPAKAI SEBAGAI KUNCI. SKU DISIMPAN SEBAGAI STRING.
# ============================================================
@st.cache_data(show_spinner=False)
def load_master_database(master_file_bytes):
    database = {}
    duplicate_skus = set()

    with pdfplumber.open(BytesIO(master_file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                tokens = line.split()

                sku_pos = next(
                    (i for i, token in enumerate(tokens)
                     if re.fullmatch(r"\d{8,14}", token)),
                    None
                )

                # Bentuk baris master:
                # kode internal | brand | nama produk | SKU/Barcode | HET Offline | ...
                if sku_pos is None or sku_pos < 2 or sku_pos + 1 >= len(tokens):
                    continue

                sku = tokens[sku_pos].strip()
                product_name = " ".join(tokens[2:sku_pos]).strip()
                price = parse_master_price(tokens[sku_pos + 1])

                if not sku or not product_name or price <= 0:
                    continue

                if sku in database:
                    duplicate_skus.add(sku)

                # Jika SKU ganda, data terakhir akan dipakai dan duplikat
                # dilaporkan di layar agar bisa diperiksa oleh admin.
                database[sku] = {
                    "sku": sku,
                    "nama_produk": product_name,
                    "harga": price
                }

    return database, sorted(duplicate_skus)


# ============================================================
# PEMBACA PDF SURAT JALAN
# HANYA membaca SKU dan QTY.
# Tidak mengambil/menggunakan teks pada kolom NAMA BARANG.
# Posisi QTY mengacu pada PDF Surat Jalan contoh yang diberikan.
# ============================================================
def extract_sku_qty(delivery_pdf_bytes):
    found = []
    errors = []

    with pdfplumber.open(BytesIO(delivery_pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2,
                keep_blank_chars=False
            )

            sku_words = [
                word for word in words
                if re.fullmatch(r"\d{8,14}", word["text"])
            ]

            for sku_word in sku_words:
                sku = sku_word["text"]
                sku_y = sku_word["top"]

                # Di format Surat Jalan contoh, QTY berada di x sekitar 410 pt.
                # Cari angka yang sejajar dengan SKU pada kolom QTY.
                qty_candidates = [
                    word for word in words
                    if 395 <= word["x0"] <= 430
                    and abs(word["top"] - sku_y) <= 2.5
                    and re.fullmatch(r"\d{1,5}", word["text"])
                ]

                if not qty_candidates:
                    errors.append(
                        f"Halaman {page_no}: QTY tidak terbaca untuk SKU {sku}."
                    )
                    continue

                qty_word = min(
                    qty_candidates,
                    key=lambda word: (abs(word["top"] - sku_y), word["x0"])
                )
                qty = int(qty_word["text"])

                if qty < 1:
                    errors.append(f"SKU {sku}: QTY harus minimal 1.")
                    continue

                found.append({"sku": sku, "qty": qty})

    # SKU sama pada beberapa baris dijumlahkan tanpa mengubah SKU.
    combined = {}
    for row in found:
        combined[row["sku"]] = combined.get(row["sku"], 0) + row["qty"]

    return [{"sku": sku, "qty": qty} for sku, qty in combined.items()], errors


# ============================================================
# PDF PESANAN
# Urutan kolom, informasi, ringkasan, catatan, tanda tangan dan
# tanggal cetak mengikuti urutan PDF PESANAN contoh.
# ============================================================
def build_order_pdf(
    dataframe,
    customer_name,
    customer_address,
    order_number,
    order_date,
    reference_number,
    notes,
    other_discount
):
    output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=13 * mm,
        leftMargin=13 * mm,
        topMargin=9 * mm,
        bottomMargin=12 * mm,
        title="PESANAN"
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="InfoSmall", parent=styles["Normal"],
        fontName="Helvetica", fontSize=7.6, leading=9.5
    ))
    styles.add(ParagraphStyle(
        name="ItemSmall", parent=styles["Normal"],
        fontName="Helvetica", fontSize=6.7, leading=7.8
    ))
    styles.add(ParagraphStyle(
        name="TableHeadSmall", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=6.7, leading=7.5,
        alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="TitleOrder", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=19, leading=22,
        alignment=TA_RIGHT
    ))
    styles.add(ParagraphStyle(
        name="NoteSmall", parent=styles["Normal"],
        fontName="Helvetica", fontSize=7.6, leading=9
    ))

    story = []

    # HEADER: logo kiri, PESANAN kanan
    if LOGO_FILE.exists():
        logo = RLImage(str(LOGO_FILE), width=38*mm, height=14*mm)
    else:
        logo = Paragraph("<b>OXAR GLOBAL</b>", styles["InfoSmall"])

    header = Table(
        [[logo, Paragraph("PESANAN", styles["TitleOrder"])]],
        colWidths=[90*mm, 90*mm],
        rowHeights=[19*mm]
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 7*mm))

    # Informasi penerima di kiri, nomor/tanggal/ref di kanan.
    recipient = [
        Paragraph(f"<b>Kepada:</b> {customer_name or '-'}", styles["InfoSmall"]),
        Paragraph(customer_address or "-", styles["InfoSmall"]),
        Spacer(1, 4*mm),
        Paragraph(customer_name or "-", styles["InfoSmall"]),
        Paragraph(customer_address or "-", styles["InfoSmall"]),
    ]

    order_info = [
        Paragraph(f"<b>No Pesanan</b> {order_number or '-'}", styles["InfoSmall"]),
        Paragraph(f"<b>Tanggal</b> {order_date.strftime('%d %b %Y')}", styles["InfoSmall"]),
        Paragraph(f"<b>No. Ref.</b> {reference_number or ''}", styles["InfoSmall"]),
    ]

    info = Table([[recipient, order_info]], colWidths=[105*mm, 75*mm])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(info)
    story.append(Spacer(1, 13*mm))

    # Tabel dengan urutan yang sama seperti PDF kedua.
    headers = [
        "NO", "SKU", "NAMA BARANG", "QTY",
        "HARGA (UNIT)", "DISKON", "HARGA SETELAH<br/>DISKON"
    ]
    table_rows = [[Paragraph(h, styles["TableHeadSmall"]) for h in headers]]

    subtotal = 0
    total_discount = 0
    total_qty = 0

    for idx, row in dataframe.reset_index(drop=True).iterrows():
        sku = str(row["SKU"])
        product_name = str(row["NAMA BARANG"])
        qty = int(row["QTY"])
        unit_price = int(row["HARGA (UNIT)"])
        discount_pct = float(row["DISKON (%)"])

        gross = qty * unit_price
        discount_amount = gross * discount_pct / 100
        net_amount = gross - discount_amount

        subtotal += gross
        total_discount += discount_amount
        total_qty += qty

        safe_name = (
            product_name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        table_rows.append([
            str(idx + 1),
            sku,
            Paragraph(safe_name, styles["ItemSmall"]),
            number_id(qty),
            rupiah(unit_price),
            percent_id(discount_pct),
            rupiah(net_amount)
        ])

    widths = [8*mm, 31*mm, 60*mm, 11*mm, 24*mm, 17*mm, 29*mm]
    product_table = Table(table_rows, colWidths=widths, repeatRows=1)
    product_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.65, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F5F6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6.7),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.7),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (3, 1), (5, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(product_table)

    # Ringkasan kanan: urutan sama dengan contoh.
    grand_total = subtotal - total_discount - float(other_discount)

    summary_data = [
        ["Total Qty", number_id(total_qty), "Sub Total", summary_id(subtotal)],
        ["", "", "Diskon", summary_id(total_discount)],
        ["", "", "Diskon Lainnya", summary_id(other_discount)],
        ["", "", "Grand Total", summary_id(grand_total)],
    ]
    summary = Table(
        summary_data,
        colWidths=[24*mm, 18*mm, 87*mm, 51*mm]
    )
    summary.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (2, 3), (3, 3), "Helvetica-Bold"),
        ("LINEABOVE", (2, 3), (3, 3), 0.8, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(summary)
    story.append(Spacer(1, 3*mm))

    # Catatan di kiri, sesuai urutan contoh.
    story.append(Paragraph("<b>Catatan :</b>", styles["NoteSmall"]))
    story.append(Paragraph(notes or "", styles["NoteSmall"]))

    # Ruang tanda tangan seperti PDF contoh.
    story.append(Spacer(1, 38*mm))
    signatures = Table(
        [
            ["Diterima Oleh,", "Dikirim Oleh,", "Hormat Kami,"],
            ["", "", ""],
            ["( ............................................... )",
             "( ............................................... )",
             "( ............................................... )"],
        ],
        colWidths=[60*mm, 60*mm, 60*mm],
        rowHeights=[7*mm, 18*mm, 7*mm]
    )
    signatures.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(signatures)
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph(
        f"Dicetak tanggal :       {datetime.now().strftime('%d %b %Y %H:%M')}",
        styles["NoteSmall"]
    ))

    doc.build(story)
    output.seek(0)
    return output.getvalue()


# ============================================================
# APLIKASI
# ============================================================
if not check_password():
    st.stop()

st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">OXAR GLOBAL • AREA ORDER SYSTEM</div>
      <h1>Surat Jalan → Pesanan</h1>
      <p>Upload surat jalan, masukkan diskon per SKU, lalu unduh PDF PESANAN.</p>
    </div>
    """,
    unsafe_allow_html=True
)

step_cols = st.columns(3)
steps = [
    ("01", "Upload Surat Jalan", "Unggah PDF sumber dari tim area."),
    ("02", "Isi Diskon", "Diskon ditentukan sendiri oleh tim area."),
    ("03", "Download Pesanan", "Hasil PDF mengikuti urutan format contoh."),
]
for col, step in zip(step_cols, steps):
    with col:
        st.markdown(
            f"""
            <div class="step-card">
              <div class="step-num">LANGKAH {step[0]}</div>
              <div class="step-title">{step[1]}</div>
              <div class="step-desc">{step[2]}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

st.write("")
st.markdown('<div class="section-heading">1. Upload dokumen Surat Jalan</div>', unsafe_allow_html=True)

if not MASTER_PDF.exists():
    st.error("Database harga belum tersedia. Administrator perlu meletakkan file master di folder aplikasi.")
    st.stop()

master_bytes = MASTER_PDF.read_bytes()
master_db, duplicate_skus = load_master_database(master_bytes)

if not master_db:
    st.error("Database harga tidak berhasil dibaca. Pastikan PDF master memiliki teks yang dapat diseleksi.")
    st.stop()

st.caption(f"Database master aktif: {len(master_db)} SKU unik.")
if duplicate_skus:
    with st.expander("Perhatian administrator: SKU duplikat pada master"):
        st.write(", ".join(duplicate_skus))

uploaded = st.file_uploader(
    "Pilih file PDF Surat Jalan",
    type=["pdf"],
    help="Gunakan PDF asli yang teksnya dapat diseleksi, bukan foto/scan."
)

if uploaded:
    try:
        source_items, extraction_errors = extract_sku_qty(uploaded.getvalue())

        for message in extraction_errors:
            st.warning(message)

        if not source_items:
            st.error(
                "SKU dan QTY belum berhasil dibaca. Pastikan PDF menggunakan "
                "format tabel Surat Jalan yang sama dan bukan hasil scan."
            )
            st.stop()

        missing_skus = [item["sku"] for item in source_items if item["sku"] not in master_db]
        if missing_skus:
            st.error("SKU berikut tidak ditemukan pada database master:")
            st.code("\n".join(missing_skus))
            st.info("Administrator perlu memperbarui database harga. SKU tidak akan diganti atau ditebak.")
            st.stop()

        rows = []
        for item in source_items:
            product = master_db[item["sku"]]
            rows.append({
                "SKU": item["sku"],
                "NAMA BARANG": product["nama_produk"],
                "QTY": item["qty"],
                "HARGA (UNIT)": product["harga"],
                "DISKON (%)": 0.0
            })

        original_df = pd.DataFrame(rows)

        st.markdown('<div class="section-heading">2. Periksa SKU dan masukkan diskon</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="note-box">
            <b>Aturan pembacaan:</b> Sistem hanya mengambil SKU dan QTY dari Surat Jalan.
            Nama produk dan harga diambil dari database master berdasarkan SKU.
            SKU, nama produk, QTY, dan harga dikunci agar tidak berubah. Tim area hanya mengisi kolom DISKON (%).
            </div>
            """,
            unsafe_allow_html=True
        )
        st.write("")

        edited_df = st.data_editor(
            original_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=["SKU", "NAMA BARANG", "QTY", "HARGA (UNIT)"],
            column_config={
                "SKU": st.column_config.TextColumn("SKU", width="medium"),
                "NAMA BARANG": st.column_config.TextColumn("NAMA BARANG", width="large"),
                "QTY": st.column_config.NumberColumn("QTY", format="%d", width="small"),
                "HARGA (UNIT)": st.column_config.NumberColumn("HARGA (UNIT)", format="Rp %d", width="medium"),
                "DISKON (%)": st.column_config.NumberColumn(
                    "DISKON (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    format="%.2f%%",
                    width="medium",
                    help="Isi diskon yang ditentukan oleh tim area. Contoh: 30 berarti 30%."
                ),
            },
            key="discount_editor"
        )

        if (
            edited_df["DISKON (%)"].isna().any()
            or (edited_df["DISKON (%)"] < 0).any()
            or (edited_df["DISKON (%)"] > 100).any()
        ):
            st.error("Diskon harus diisi antara 0 sampai 100 persen.")
            st.stop()

        # Perhitungan hanya mengubah nominal; tidak menentukan diskon.
        calc = edited_df.copy()
        calc["SUBTOTAL BARIS"] = calc["QTY"] * calc["HARGA (UNIT)"]
        calc["NILAI DISKON"] = calc["SUBTOTAL BARIS"] * calc["DISKON (%)"] / 100
        calc["HARGA SETELAH DISKON"] = calc["SUBTOTAL BARIS"] - calc["NILAI DISKON"]

        subtotal = float(calc["SUBTOTAL BARIS"].sum())
        discount_total = float(calc["NILAI DISKON"].sum())

        st.markdown('<div class="section-heading">3. Informasi PESANAN</div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            customer_name = st.text_input(
                "Kepada / Nama toko",
                placeholder="Contoh: [ Consignment ] Princess Cosmetic Kayutangi"
            )
            customer_address = st.text_area(
                "Alamat toko",
                placeholder="Masukkan alamat lengkap toko",
                height=82
            )
            notes = st.text_area(
                "Catatan",
                placeholder="Contoh: Sell Out 1-31 Oktober 2026",
                height=75
            )
        with right:
            order_number = st.text_input(
                "No Pesanan",
                placeholder="Contoh: SO-000494064"
            )
            order_date = st.date_input("Tanggal", value=date.today(), format="DD/MM/YYYY")
            reference_number = st.text_input("No. Ref.", placeholder="Opsional")
            other_discount = st.number_input(
                "Diskon Lainnya (Rp)",
                min_value=0,
                value=0,
                step=1000,
                help="Isi 0 jika tidak ada diskon lainnya."
            )

        grand_total = subtotal - discount_total - float(other_discount)
        if grand_total < 0:
            st.error("Grand Total tidak boleh negatif. Periksa Diskon Lainnya.")
            st.stop()

        st.markdown('<div class="section-heading">4. Ringkasan perhitungan</div>', unsafe_allow_html=True)
        a, b, c, d = st.columns(4)
        a.metric("Total Qty", number_id(edited_df["QTY"].sum()))
        b.metric("Sub Total", rupiah(subtotal))
        c.metric("Diskon", rupiah(discount_total))
        d.metric("Grand Total", rupiah(grand_total))

        st.caption("Diskon pada kolom tabel PDF akan tetap ditampilkan sebagai persentase, misalnya 30,00%.")

        st.markdown('<div class="section-heading">5. Buat PDF PESANAN</div>', unsafe_allow_html=True)
        if st.button("Buat PDF PESANAN", type="primary", use_container_width=True):
            if not customer_name.strip():
                st.error("Nama toko pada bagian Kepada wajib diisi.")
            elif not order_number.strip():
                st.error("Nomor Pesanan wajib diisi.")
            else:
                pdf_bytes = build_order_pdf(
                    edited_df,
                    customer_name.strip(),
                    customer_address.strip(),
                    order_number.strip(),
                    order_date,
                    reference_number.strip(),
                    notes.strip(),
                    other_discount
                )
                safe_order_no = re.sub(r"[^A-Za-z0-9_-]", "-", order_number.strip())
                st.session_state["generated_pdf"] = pdf_bytes
                st.session_state["generated_filename"] = f"Pesanan_{safe_order_no}.pdf"
                st.success("PDF PESANAN berhasil dibuat. Periksa lalu download.")

        if "generated_pdf" in st.session_state:
            st.download_button(
                "Download PDF PESANAN",
                data=st.session_state["generated_pdf"],
                file_name=st.session_state["generated_filename"],
                mime="application/pdf",
                use_container_width=True
            )

    except Exception as exc:
        st.error(f"Terjadi kesalahan saat membaca atau membuat PDF: {exc}")

else:
    st.info("Mulai dengan mengunggah PDF Surat Jalan. Setelah diunggah, tabel SKU akan muncul otomatis.")

st.markdown("---")
st.caption("OXAR GLOBAL • Surat Jalan ke PESANAN | Periksa kembali dokumen sebelum digunakan.")
