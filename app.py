
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage
)

# =========================================================
# 1. KONFIGURASI APLIKASI
# =========================================================

st.set_page_config(
    page_title="Surat Jalan - OXAR GLOBAL",
    page_icon="📄",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent

MASTER_PDF = BASE_DIR / "Data Harga - Google Spreadsheet.pdf"
LOGO_FILE = BASE_DIR / "logo_oxar.jpg"


# =========================================================
# 2. FORMAT ANGKA
# =========================================================

def digits_only(value):
    return re.sub(r"[^0-9]", "", str(value))


def parse_price(value):
    digits = digits_only(value)
    return int(digits) if digits else 0


def rupiah(value):
    return "Rp" + f"{int(round(float(value))):,}".replace(",", ".")


def format_number(value):
    return f"{int(round(float(value))):,}".replace(",", ".")


def format_total(value):
    return (
        f"{float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def format_percent(value):
    return f"{float(value):.2f}".replace(".", ",") + "%"


def escape_html(value):
    value = str(value or "-")
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# =========================================================
# 3. MEMBACA DATABASE MASTER BERDASARKAN SKU
# =========================================================

@st.cache_data(show_spinner=False)
def load_master_database(master_bytes):

    database = {}

    with pdfplumber.open(BytesIO(master_bytes)) as pdf:

        for page in pdf.pages:

            text = page.extract_text() or ""

            for line in text.splitlines():

                tokens = line.split()

                # SKU barcode biasanya 8-14 digit
                sku_position = next(
                    (
                        i for i, token in enumerate(tokens)
                        if re.fullmatch(r"\d{8,14}", token)
                    ),
                    None
                )

                if sku_position is None:
                    continue

                if sku_position < 2:
                    continue

                if sku_position + 1 >= len(tokens):
                    continue

                sku = tokens[sku_position]

                # Nama produk hanya sebagai informasi database.
                # Pencocokan produk tetap menggunakan SKU.
                nama_produk = " ".join(
                    tokens[2:sku_position]
                ).strip()

                harga = parse_price(tokens[sku_position + 1])

                if sku and harga > 0:

                    database[sku] = {
                        "sku": sku,
                        "nama_produk": nama_produk,
                        "harga": harga
                    }

    return database


# =========================================================
# 4. MEMBACA HEADER SURAT JALAN
# =========================================================

def extract_header(pdf_bytes):

    result = {
        "dari": "",
        "tujuan": "",
        "no_transfer": "",
        "tanggal": "",
        "catatan": ""
    }

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:

        text = "\n".join(
            page.extract_text() or ""
            for page in pdf.pages
        )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # -----------------------------------------------------
    # DARI dan NO TRANSFER bisa berada pada satu baris
    # -----------------------------------------------------

    match = re.search(
        r"DARI\s*:\s*(.*?)\s+No\.?\s*Transfer\s+([A-Z0-9\-]+)",
        text,
        re.IGNORECASE
    )

    if match:

        result["dari"] = match.group(1).strip()
        result["no_transfer"] = match.group(2).strip()

    # -----------------------------------------------------
    # TANGGAL
    # -----------------------------------------------------

    match = re.search(
        r"Tanggal\s+(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        result["tanggal"] = match.group(1).strip()

    # -----------------------------------------------------
    # TUJUAN
    # Contoh:
    # TUJUAN : [ Consignment ] Tanggal 28 Oct 2026
    # Princess Cosmetic
    # Kayutangi
    # -----------------------------------------------------

    tujuan_started = False
    tujuan_parts = []

    for line in lines:

        if re.search(r"TUJUAN\s*:", line, re.IGNORECASE):

            tujuan_started = True

            # Ambil bagian setelah TUJUAN
            bagian = re.split(
                r"TUJUAN\s*:",
                line,
                maxsplit=1,
                flags=re.IGNORECASE
            )[1]

            # Hilangkan tanggal yang berada di baris sama
            bagian = re.sub(
                r"\s+Tanggal\s+\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}.*$",
                "",
                bagian,
                flags=re.IGNORECASE
            )

            if bagian.strip():
                tujuan_parts.append(bagian.strip())

            continue

        if tujuan_started:

            # Berhenti ketika menemukan tabel
            if re.search(r"\bNO\s+SKU\b", line, re.IGNORECASE):
                break

            # Lewati informasi header lain
            if re.match(
                r"^(DARI|No\.?\s*Transfer|Tanggal)\b",
                line,
                re.IGNORECASE
            ):
                continue

            tujuan_parts.append(line.strip())

    result["tujuan"] = " ".join(tujuan_parts).strip()

    # -----------------------------------------------------
    # CATATAN
    # -----------------------------------------------------

    match = re.search(
        r"Catatan\s*:\s*(.*?)(?=\n\s*Dicetak\s+tanggal|\Z)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:

        result["catatan"] = " ".join(
            line.strip()
            for line in match.group(1).splitlines()
            if line.strip()
        )

    return result


# =========================================================
# 5. MEMBACA SKU DAN QTY DARI PDF
# =========================================================

def extract_sku_qty(pdf_bytes):

    items = []
    errors = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:

        for page_number, page in enumerate(pdf.pages, start=1):

            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2
            )

            sku_words = [
                word for word in words
                if re.fullmatch(r"\d{8,14}", word["text"])
            ]

            for sku_word in sku_words:

                sku = sku_word["text"]
                sku_y = sku_word["top"]

                # Posisi kolom QTY berdasarkan PDF contoh
                qty_candidates = [
                    word for word in words
                    if 395 <= word["x0"] <= 425
                    and abs(word["top"] - sku_y) <= 3
                    and re.fullmatch(r"\d{1,5}", word["text"])
                ]

                if not qty_candidates:

                    errors.append(
                        f"QTY tidak ditemukan untuk SKU {sku} "
                        f"di halaman {page_number}."
                    )

                    continue

                qty_word = min(
                    qty_candidates,
                    key=lambda word: abs(word["top"] - sku_y)
                )

                qty = int(qty_word["text"])

                if qty > 0:

                    items.append({
                        "sku": sku,
                        "qty": qty
                    })

    # Gabungkan SKU yang sama
    combined = {}

    for item in items:

        sku = item["sku"]

        combined[sku] = (
            combined.get(sku, 0) + item["qty"]
        )

    rows = [
        {"sku": sku, "qty": qty}
        for sku, qty in combined.items()
    ]

    return rows, errors


# =========================================================
# 6. MEMBUAT PDF SURAT JALAN
# =========================================================

def build_pdf(df, header, diskon):

    output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="SmallCustom",
            fontName="Helvetica",
            fontSize=8,
            leading=10
        )
    )

    styles.add(
        ParagraphStyle(
            name="TitleCustom",
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=24,
            alignment=TA_RIGHT
        )
    )

    styles.add(
        ParagraphStyle(
            name="ProductCustom",
            fontName="Helvetica",
            fontSize=7.5,
            leading=9
        )
    )

    styles.add(
        ParagraphStyle(
            name="HeaderCustom",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            alignment=TA_CENTER
        )
    )

    story = []

    # -----------------------------------------------------
    # HEADER LOGO DAN JUDUL
    # -----------------------------------------------------

    if LOGO_FILE.exists():

        logo = RLImage(
            str(LOGO_FILE),
            width=39 * mm,
            height=15 * mm
        )

    else:

        logo = Paragraph(
            "<b>OXAR GLOBAL</b>",
            styles["SmallCustom"]
        )

    header_table = Table(
        [[
            logo,
            Paragraph("SURAT JALAN", styles["TitleCustom"])
        ]],
        colWidths=[92 * mm, 88 * mm],
        rowHeights=[20 * mm]
    )

    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    story.append(header_table)
    story.append(Spacer(1, 8 * mm))

    # -----------------------------------------------------
    # INFORMASI DARI DAN TUJUAN
    # TUJUAN TIDAK DITAMPILKAN DUA KALI
    # -----------------------------------------------------

    left_info = [
        Paragraph(
            f"<b>DARI:</b> {escape_html(header['dari'])}",
            styles["SmallCustom"]
        ),

        Spacer(1, 3 * mm),

        Paragraph(
            f"<b>TUJUAN:</b> {escape_html(header['tujuan'])}",
            styles["SmallCustom"]
        )
    ]

    right_info = [
        Paragraph(
            f"<b>No. Transfer:</b> "
            f"{escape_html(header['no_transfer'])}",
            styles["SmallCustom"]
        ),

        Paragraph(
            f"<b>Tanggal:</b> "
            f"{escape_html(header['tanggal'])}",
            styles["SmallCustom"]
        )
    ]

    info_table = Table(
        [[left_info, right_info]],
        colWidths=[112 * mm, 68 * mm]
    )

    info_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    story.append(info_table)
    story.append(Spacer(1, 12 * mm))

    # -----------------------------------------------------
    # TABEL PRODUK
    # -----------------------------------------------------

    table_data = [[
        Paragraph("NO", styles["HeaderCustom"]),
        Paragraph("SKU", styles["HeaderCustom"]),
        Paragraph("NAMA BARANG", styles["HeaderCustom"]),
        Paragraph("QTY", styles["HeaderCustom"]),
        Paragraph("HARGA (UNIT)", styles["HeaderCustom"]),
        Paragraph("DISKON", styles["HeaderCustom"]),
        Paragraph("HARGA SETELAH<br/>DISKON", styles["HeaderCustom"])
    ]]

    subtotal = 0
    total_diskon = 0
    total_qty = 0

    for index, row in df.reset_index(drop=True).iterrows():

        sku = str(row["SKU"])
        nama = str(row["NAMA BARANG"])
        qty = int(row["QTY"])
        harga = int(row["HARGA (UNIT)"])

        nilai_subtotal = qty * harga

        # Diskon yang sama untuk semua produk
        nilai_diskon = nilai_subtotal * diskon / 100

        harga_setelah_diskon = (
            nilai_subtotal - nilai_diskon
        )

        subtotal += nilai_subtotal
        total_diskon += nilai_diskon
        total_qty += qty

        table_data.append([
            str(index + 1),
            sku,
            Paragraph(
                escape_html(nama),
                styles["ProductCustom"]
            ),
            format_number(qty),
            rupiah(harga),
            format_percent(diskon),
            rupiah(harga_setelah_diskon)
        ])

    column_widths = [
        8 * mm,
        30 * mm,
        61 * mm,
        11 * mm,
        25 * mm,
        18 * mm,
        29 * mm
    ]

    product_table = Table(
        table_data,
        colWidths=column_widths,
        repeatRows=1
    )

    product_table.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.7, colors.black),

            ("BACKGROUND", (0, 0), (-1, 0),
             colors.HexColor("#F1F3F5")),

            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("ALIGN", (0, 0), (-1, 0), "CENTER"),

            ("ALIGN", (0, 1), (1, -1), "CENTER"),

            ("ALIGN", (3, 1), (5, -1), "CENTER"),

            ("ALIGN", (4, 1), (4, -1), "RIGHT"),

            ("ALIGN", (6, 1), (6, -1), "RIGHT"),

            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),

            ("FONTSIZE", (0, 0), (-1, -1), 7.5),

            ("LEFTPADDING", (0, 0), (-1, -1), 3),

            ("RIGHTPADDING", (0, 0), (-1, -1), 3),

            ("TOPPADDING", (0, 0), (-1, -1), 5),

            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )

    story.append(product_table)

    # -----------------------------------------------------
    # RINGKASAN PERHITUNGAN
    # -----------------------------------------------------

    grand_total = subtotal - total_diskon

    summary_data = [
        [
            "Total Qty",
            format_number(total_qty),
            "Sub Total",
            format_total(subtotal)
        ],

        [
            "",
            "",
            "Diskon",
            format_total(total_diskon)
        ],

        [
            "",
            "",
            "Diskon Lainnya",
            format_total(0)
        ],

        [
            "",
            "",
            "Grand Total",
            format_total(grand_total)
        ]
    ]

    summary_table = Table(
        summary_data,
        colWidths=[
            25 * mm,
            18 * mm,
            86 * mm,
            53 * mm
        ]
    )

    summary_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),

            ("FONTSIZE", (0, 0), (-1, -1), 8),

            ("ALIGN", (0, 0), (1, -1), "CENTER"),

            ("ALIGN", (2, 0), (2, -1), "RIGHT"),

            ("ALIGN", (3, 0), (3, -1), "RIGHT"),

            ("FONTNAME", (2, 3), (3, 3),
             "Helvetica-Bold"),

            ("LINEABOVE", (2, 3), (3, 3),
             0.8, colors.black),

            ("TOPPADDING", (0, 0), (-1, -1), 3),

            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )

    story.append(summary_table)
    story.append(Spacer(1, 8 * mm))

    # -----------------------------------------------------
    # CATATAN
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "<b>Catatan:</b>",
            styles["SmallCustom"]
        )
    )

    story.append(
        Paragraph(
            escape_html(header["catatan"]),
            styles["SmallCustom"]
        )
    )

    story.append(Spacer(1, 32 * mm))

    # -----------------------------------------------------
    # TANDA TANGAN
    # -----------------------------------------------------

    signature_table = Table(
        [
            [
                "Diterima Oleh,",
                "Dikirim Oleh,",
                "Hormat Kami,"
            ],

            ["", "", ""],

            [
                "( .................................... )",
                "( .................................... )",
                "( .................................... )"
            ]
        ],
        colWidths=[
            60 * mm,
            60 * mm,
            60 * mm
        ],
        rowHeights=[
            7 * mm,
            17 * mm,
            7 * mm
        ]
    )

    signature_table.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),

            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),

            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ])
    )

    story.append(signature_table)

    story.append(Spacer(1, 7 * mm))

    story.append(
        Paragraph(
            "Dicetak tanggal: "
            + datetime.now().strftime("%d %b %Y %H:%M"),
            styles["ProductCustom"]
        )
    )

    doc.build(story)

    output.seek(0)

    return output.getvalue()


# =========================================================
# 7. TAMPILAN APLIKASI STREAMLIT
# =========================================================

st.markdown("""
<style>

.stApp {
    background-color: #f5f7fb;
}

.block-container {
    max-width: 1180px;
    padding-top: 1.5rem;
}

.hero {
    background: linear-gradient(
        120deg,
        #12243a,
        #1d4260,
        #287a78
    );

    color: white;
    padding: 26px 30px;
    border-radius: 17px;
    margin-bottom: 20px;
}

.hero h1 {
    color: white;
    font-size: 29px;
    margin-bottom: 6px;
}

.hero p {
    color: #e5eef3;
    margin: 0;
}

.section-title {
    font-size: 19px;
    font-weight: 750;
    color: #172b42;
    margin: 20px 0 10px;
}

.hint {
    background: #eaf4f3;
    border-left: 4px solid #23877e;
    padding: 13px;
    border-radius: 8px;
    color: #244b50;
    margin-bottom: 12px;
}

</style>

<div class="hero">
    <h1>📄 SURAT JALAN OXAR GLOBAL</h1>
    <p>
        Upload surat jalan, tentukan satu diskon untuk
        seluruh produk, lalu download PDF.
    </p>
</div>
""", unsafe_allow_html=True)


# =========================================================
# 8. MEMUAT DATABASE
# =========================================================

if not MASTER_PDF.exists():

    st.error(
        "Database harga tidak ditemukan. "
        "Pastikan file Data Harga - Google Spreadsheet.pdf "
        "ada di repository GitHub."
    )

    st.stop()


master_db = load_master_database(
    MASTER_PDF.read_bytes()
)

if not master_db:

    st.error("Database SKU tidak berhasil dibaca.")

    st.stop()


st.success(
    f"Database harga aktif: {len(master_db):,} SKU."
)


# =========================================================
# 9. UPLOAD PDF SURAT JALAN
# =========================================================

st.markdown(
    '<div class="section-title">1. Upload Surat Jalan</div>',
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader(
    "Pilih file PDF Surat Jalan",
    type=["pdf"],
    help="Upload PDF Surat Jalan asli."
)


if uploaded_file:

    pdf_bytes = uploaded_file.getvalue()

    header = extract_header(pdf_bytes)

    items, errors = extract_sku_qty(pdf_bytes)

    for error in errors:

        st.warning(error)

    if not items:

        st.error(
            "SKU dan QTY tidak berhasil dibaca dari PDF."
        )

        st.stop()

    # -----------------------------------------------------
    # CEK SKU DI DATABASE
    # -----------------------------------------------------

    missing_skus = [
        item["sku"]
        for item in items
        if item["sku"] not in master_db
    ]

    if missing_skus:

        st.error(
            "SKU berikut tidak ditemukan dalam database harga:"
        )

        st.code("\n".join(missing_skus))

        st.stop()

    # -----------------------------------------------------
    # INFORMASI HEADER
    # -----------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '2. Informasi Surat Jalan'
        '</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)

    with col1:

        st.text_input(
            "DARI",
            value=header["dari"] or "Tidak terbaca",
            disabled=True
        )

        st.text_area(
            "TUJUAN",
            value=header["tujuan"] or "Tidak terbaca",
            disabled=True,
            height=80
        )

    with col2:

        st.text_input(
            "No. Transfer",
            value=header["no_transfer"] or "Tidak terbaca",
            disabled=True
        )

        st.text_input(
            "Tanggal",
            value=header["tanggal"] or "Tidak terbaca",
            disabled=True
        )

        st.text_area(
            "Catatan",
            value=header["catatan"] or "-",
            disabled=True,
            height=60
        )

    # -----------------------------------------------------
    # INPUT SATU DISKON UNTUK SEMUA SKU
    # -----------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '3. Pengaturan Diskon'
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="hint">
        <b>Perhatian:</b> Diskon hanya diisi satu kali
        untuk seluruh produk dalam satu Surat Jalan.
        Tidak perlu mengisi diskon masing-masing SKU.
        </div>
        """,
        unsafe_allow_html=True
    )

    diskon = st.number_input(
        "Masukkan Diskon Seluruh Produk (%)",
        min_value=0.0,
        max_value=100.0,
        value=20.0,
        step=1.0,
        format="%.2f",
        help="Contoh: masukkan 30 untuk diskon 30%."
    )

    st.caption(
        f"Diskon yang akan diterapkan ke seluruh produk: "
        f"{format_percent(diskon)}"
    )

    # -----------------------------------------------------
    # MEMBUAT DATA PRODUK
    # -----------------------------------------------------

    product_data = []

    for item in items:

        product = master_db[item["sku"]]

        product_data.append({

            "SKU": item["sku"],

            "NAMA BARANG": product["nama_produk"],

            "QTY": item["qty"],

            "HARGA (UNIT)": product["harga"],

            "DISKON (%)": diskon

        })

    df = pd.DataFrame(product_data)

    # -----------------------------------------------------
    # PREVIEW
    # -----------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '4. Preview Produk dan Perhitungan'
        '</div>',
        unsafe_allow_html=True
    )

    preview = df.copy()

    preview["SUBTOTAL"] = (
        preview["QTY"] * preview["HARGA (UNIT)"]
    )

    preview["NILAI DISKON"] = (
        preview["SUBTOTAL"] * diskon / 100
    )

    preview["HARGA SETELAH DISKON"] = (
        preview["SUBTOTAL"] - preview["NILAI DISKON"]
    )

    display_df = preview.copy()

    display_df["HARGA (UNIT)"] = (
        display_df["HARGA (UNIT)"].map(rupiah)
    )

    display_df["DISKON (%)"] = (
        display_df["DISKON (%)"].map(format_percent)
    )

    display_df["SUBTOTAL"] = (
        display_df["SUBTOTAL"].map(rupiah)
    )

    display_df["NILAI DISKON"] = (
        display_df["NILAI DISKON"].map(rupiah)
    )

    display_df["HARGA SETELAH DISKON"] = (
        display_df["HARGA SETELAH DISKON"].map(rupiah)
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # -----------------------------------------------------
    # RINGKASAN
    # -----------------------------------------------------

    total_qty = int(preview["QTY"].sum())

    subtotal = float(preview["SUBTOTAL"].sum())

    total_diskon = float(
        preview["NILAI DISKON"].sum()
    )

    grand_total = subtotal - total_diskon

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total Qty",
        format_number(total_qty)
    )

    col2.metric(
        "Sub Total",
        rupiah(subtotal)
    )

    col3.metric(
        "Total Diskon",
        rupiah(total_diskon)
    )

    col4.metric(
        "Grand Total",
        rupiah(grand_total)
    )

    # -----------------------------------------------------
    # GENERATE PDF
    # -----------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '5. Generate PDF Surat Jalan'
        '</div>',
        unsafe_allow_html=True
    )

    if st.button(
        "GENERATE PDF SURAT JALAN",
        type="primary",
        use_container_width=True
    ):

        if not header["dari"]:

            st.error("Informasi DARI tidak terbaca dari PDF.")

        elif not header["tujuan"]:

            st.error("Informasi TUJUAN tidak terbaca dari PDF.")

        else:

            pdf_output = build_pdf(
                df,
                header,
                diskon
            )

            nomor_file = re.sub(
                r"[^A-Za-z0-9_-]",
                "-",
                header["no_transfer"] or "hasil"
            )

            st.session_state["pdf_surat_jalan"] = pdf_output

            st.session_state["nama_file"] = (
                f"Surat_Jalan_{nomor_file}.pdf"
            )

            st.success(
                "PDF Surat Jalan berhasil dibuat!"
            )

    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    if "pdf_surat_jalan" in st.session_state:

        st.download_button(
            label="DOWNLOAD PDF SURAT JALAN",
            data=st.session_state["pdf_surat_jalan"],
            file_name=st.session_state["nama_file"],
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )

else:

    st.info(
        "Silakan upload PDF Surat Jalan. "
        "Sistem akan membaca informasi, SKU, dan QTY secara otomatis."
    )


st.markdown("---")

st.caption(
    "OXAR GLOBAL | Sistem Pembuatan Surat Jalan"
)
