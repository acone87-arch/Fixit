from io import BytesIO

from pypdf import PdfReader
from reportlab.lib.units import mm

from app.services.equipment_label_pdf import EquipmentLabel, build_single_label_pdf
from app.services.inventory_pdf import build_inventory_pdf


def _links(pdf: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf))
    return [annotation.get_object()["/A"]["/URI"] for page in reader.pages for annotation in page.get("/Annots", [])]


def test_single_and_batch_labels_share_size_content_and_safe_url():
    token = "ec98bfa6-9050-4681-8144-7834da3423a0"
    base = "https://fixit.example"
    single = build_single_label_pdf(EquipmentLabel(token=token, site_name="Главный объект", equipment_name="Очень длинное название оборудования " * 8, inventory_number=7, batch_id="12345678-rest"), base)
    batch = build_inventory_pdf("Главный объект", "12345678-rest", [(7, token)], base)
    single_reader = PdfReader(BytesIO(single))
    assert round(float(single_reader.pages[0].mediabox.width), 2) == round(90 * mm, 2)
    assert round(float(single_reader.pages[0].mediabox.height), 2) == round(60 * mm, 2)
    expected = f"{base}/e/{token}"
    assert _links(single) == [expected]
    assert _links(batch) == [expected]
    assert "FIXIT" in single_reader.pages[0].extract_text()


def test_optional_label_fields_do_not_break_export():
    pdf = build_single_label_pdf(EquipmentLabel(token="token", site_name="", equipment_name=None), "http://localhost:8000/")
    assert pdf.startswith(b"%PDF") and _links(pdf) == ["http://localhost:8000/e/token"]
