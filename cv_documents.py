"""CV services. The explicit core argument preserves shared validation and providers."""
from __future__ import annotations
from typing import Any
import io

def safe_markup(core, value: Any) -> str:
    import html

    return html.escape(str(value), quote=True).replace("\n", "<br/>")


def make_docx(core, draft_data: dict[str, Any]) -> io.BytesIO:
    draft_data = core.cv_public_content(draft_data)
    document = core.Document()
    section = document.sections[0]
    section.page_width = core.Inches(8.27)
    section.page_height = core.Inches(11.69)
    section.top_margin = core.Inches(0.38)
    section.bottom_margin = core.Inches(0.38)
    section.left_margin = core.Inches(0.43)
    section.right_margin = core.Inches(0.43)
    normal = document.styles["Normal"]
    normal.font.name = "Arial Narrow"
    normal.font.size = core.Pt(8)
    normal.font.color.rgb = core.RGBColor(41, 48, 43)
    normal.paragraph_format.space_after = core.Pt(1)
    template = core.selected_template(
        {"template": draft_data.get("template")},
        {"position": draft_data.get("position", "")},
    )
    accent_rgb = core.rgb_from_hex(core.ACCENTS[template])
    candidate = draft_data["candidate"]
    layout = document.add_table(rows=1, cols=2)
    layout.autofit = False
    layout.columns[0].width = core.Inches(2.0)
    layout.columns[1].width = core.Inches(5.36)
    left, right = layout.rows[0].cells
    left.width = core.Inches(2.0)
    right.width = core.Inches(5.36)

    def set_cell_spacing(cell: Any) -> None:
        cell.vertical_alignment = core.WD_CELL_VERTICAL_ALIGNMENT.TOP

    def set_cell_background(cell: Any, color: str) -> None:
        cell_properties = cell._tc.get_or_add_tcPr()
        shading = core.OxmlElement("w:shd")
        shading.set(core.qn("w:fill"), color.removeprefix("#"))
        cell_properties.append(shading)

    for cell in (left, right):
        set_cell_spacing(cell)
    set_cell_background(left, core.TEMPLATE_SIDEBARS[template])
    table_properties = layout._tbl.tblPr
    borders = core.OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = core.OxmlElement(f"w:{edge}")
        border.set(core.qn("w:val"), "nil")
        borders.append(border)
    table_properties.append(borders)

    def add_text(
        cell: Any,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        size: float = 8,
        color: core.RGBColor | None = None,
        centered: bool = False,
        underline: bool = False,
    ) -> Any:
        paragraph = (
            cell.paragraphs[0]
            if len(cell.paragraphs) == 1
            and not cell.paragraphs[0].text
            and not cell.paragraphs[0].runs
            else cell.add_paragraph()
        )
        paragraph.paragraph_format.space_before = core.Pt(0)
        paragraph.paragraph_format.space_after = core.Pt(1)
        paragraph.paragraph_format.line_spacing = 0.95
        if centered:
            paragraph.alignment = core.WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(text)
        run.font.name = "Arial Narrow"
        run.font.size = core.Pt(size)
        run.bold = bold
        run.italic = italic
        run.underline = underline
        if color:
            run.font.color.rgb = color
        return paragraph

    def add_section(cell: Any, text: str) -> None:
        add_text(
            cell,
            text.upper(),
            bold=True,
            size=10,
            color=core.RGBColor(*accent_rgb),
        ).paragraph_format.space_before = core.Pt(5)

    def add_bullet(cell: Any, text: str, *, italic: bool = False) -> None:
        add_text(cell, f"•  {text}", italic=italic, size=7.5)

    photo_path = core.current_photo_path()
    if photo_path.is_file():
        paragraph = left.paragraphs[0]
        paragraph.alignment = core.WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = core.Pt(7)
        paragraph.add_run().add_picture(
            str(photo_path), width=core.Inches(1.25), height=core.Inches(1.62)
        )
    add_text(
        left,
        candidate["name"],
        bold=True,
        italic=True,
        size=13,
        centered=True,
    )
    add_text(left, "Cédula:", bold=True, centered=True)
    add_text(left, candidate["national_id"], bold=True, centered=True)
    add_text(left, candidate["address"], bold=True, centered=True)
    add_text(
        left,
        f"Residente en:\n{candidate['residence']}",
        bold=True,
        centered=True,
    )
    add_text(left, "Teléfonos:", bold=True, centered=True)
    for index, phone in enumerate(candidate["phones"], start=1):
        add_text(left, f"{index}.     {phone}", bold=True, centered=True)
    add_text(left, "Email:", bold=True, centered=True)
    add_text(
        left,
        candidate["email"],
        bold=True,
        centered=True,
        color=core.RGBColor(0, 0, 238),
        underline=True,
    )
    add_section(left, "Habilidades:")
    for skill in draft_data["skills"]:
        add_bullet(left, skill, italic=False)

    add_section(right, "Sobre mi")
    add_text(right, draft_data["summary"], italic=True, size=11)
    def add_projects():
        if not draft_data.get("projects"):
            return
        add_section(right, "Proyectos y experiencia práctica")
        for project in draft_data["projects"]:
            add_text(right, project["title"], bold=True, size=10)
            add_text(right, core._short_text(project["description"], 300), size=9)
            if project.get("technologies"):
                add_text(right, "Tecnologías: " + ", ".join(project["technologies"][:8]), size=8)
    if draft_data.get("project_focus"):
        add_projects()
    add_section(right, "Formación académica")
    add_text(right, "Estudios Académicos", bold=True, underline=True)
    for item in draft_data["education"]:
        add_bullet(right, f"{item['institution']} ({item['title']})", italic=True)
    add_text(right, "Cursos Realizados", bold=True, underline=True)
    for item in draft_data["courses"]:
        add_bullet(
            right,
            f"{item['title']}     {item['institution']}",
            italic=True,
        )

    if draft_data["experiences"]:
        add_section(right, draft_data.get("experience_heading", "Experiencia laboral"))
    for experience in draft_data["experiences"]:
        role = add_text(
            right,
            f"•  {experience['title']}:\t{experience['employer']}",
            bold=True,
            italic=True,
        )
        role.paragraph_format.space_before = core.Pt(3)
        for responsibility in experience["selected_responsibilities"]:
            if isinstance(responsibility, dict):
                add_bullet(
                    right,
                    f"{responsibility['employer']}: {responsibility['text']}",
                    italic=True,
                )
            else:
                add_bullet(right, responsibility, italic=True)

    if not draft_data.get("project_focus"):
        add_projects()
    add_section(right, "Referencias personales")
    references = draft_data["references"]
    for start in range(0, len(references), 2):
        row = right.add_table(rows=1, cols=2)
        row.autofit = False
        row.columns[0].width = core.Inches(2.55)
        row.columns[1].width = core.Inches(2.55)
        for cell, item in zip(row.rows[0].cells, references[start : start + 2]):
            cell.vertical_alignment = core.WD_CELL_VERTICAL_ALIGNMENT.TOP
            add_text(
                cell,
                f"•  {item['name']}\n({item['role']})\nCel. {item['phone']}",
                italic=True,
                size=7,
            )
    output = core.io.BytesIO()
    document.save(output)
    output.seek(0)
    return output


def make_pdf(core,
    draft_data: dict[str, Any],
) -> io.BytesIO:
    draft_data = core.cv_public_content(draft_data)
    output = core.io.BytesIO()
    template = core.selected_template(
        {"template": draft_data.get("template")},
        {"position": draft_data.get("position", "")},
    )
    accent = core.colors.HexColor(core.ACCENTS[template])
    sidebar = core.colors.HexColor(core.TEMPLATE_SIDEBARS[template])
    ink = core.colors.HexColor("#29302B")
    styles = {
        "section": core.ParagraphStyle(
            "KitchenSection",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=12.5,
            textColor=accent,
            spaceBefore=7,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "left": core.ParagraphStyle(
            "KitchenLeft",
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=10.2,
            textColor=ink,
            alignment=core.TA_CENTER,
            spaceAfter=3,
        ),
        "leftSmall": core.ParagraphStyle(
            "KitchenLeftSmall",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=8.5,
            textColor=ink,
            alignment=core.TA_CENTER,
            spaceAfter=3,
        ),
        "name": core.ParagraphStyle(
            "KitchenName",
            fontName="Helvetica-Bold",
            fontSize=14.5,
            leading=16,
            textColor=ink,
            alignment=core.TA_CENTER,
            spaceAfter=5,
        ),
        "objective": core.ParagraphStyle(
            "KitchenObjective",
            fontName="Helvetica-Oblique",
            fontSize=12.2,
            leading=14.8,
            textColor=ink,
            alignment=core.TA_JUSTIFY,
            spaceAfter=2,
        ),
        "subheading": core.ParagraphStyle(
            "KitchenSubheading",
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=10.7,
            textColor=ink,
            spaceBefore=2,
            spaceAfter=1,
            keepWithNext=True,
        ),
        "experience": core.ParagraphStyle(
            "KitchenExperience",
            fontName="Helvetica-BoldOblique",
            fontSize=9.2,
            leading=10.7,
            textColor=ink,
            spaceBefore=2,
            spaceAfter=1,
            keepWithNext=True,
        ),
        "bullet": core.ParagraphStyle(
            "KitchenBullet",
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=10.5,
            textColor=ink,
            leftIndent=8,
            firstLineIndent=-6,
            spaceAfter=0.5,
        ),
        "reference": core.ParagraphStyle(
            "KitchenReference",
            fontName="Helvetica-Oblique",
            fontSize=8.2,
            leading=9.5,
            textColor=ink,
            spaceAfter=0,
        ),
    }
    candidate = draft_data["candidate"]
    left_content: list[Any] = []
    right_content: list[Any] = []
    photo_path = core.current_photo_path()
    if photo_path.is_file():
        left_content.append(
            core.PdfImage(str(photo_path), width=29 * core.mm, height=37 * core.mm)
        )
        left_content[-1].hAlign = "CENTER"
        left_content.append(core.Spacer(1, 3 * core.mm))
    left_content.extend(
        [
            core.Paragraph(core.safe_markup(candidate["name"]), styles["name"]),
            core.Paragraph("<b>Cédula:</b>", styles["left"]),
            core.Paragraph(core.safe_markup(candidate["national_id"]), styles["left"]),
            core.Paragraph(core.safe_markup(candidate["address"]), styles["left"]),
            core.Paragraph(
                core.safe_markup(f"Residente en: {candidate['residence']}"),
                styles["left"],
            ),
            core.Paragraph("<b>Teléfonos:</b>", styles["left"]),
        ]
    )
    for index, phone in enumerate(candidate["phones"], start=1):
        left_content.append(
            core.Paragraph(core.safe_markup(f"{index}. {phone}"), styles["left"])
        )
    left_content.extend(
        [
            core.Paragraph("<b>Email:</b>", styles["left"]),
            core.Paragraph(core.safe_markup(candidate["email"]), styles["leftSmall"]),
            core.Paragraph("HABILIDADES:", styles["section"]),
        ]
    )
    for skill in draft_data["skills"]:
        left_content.append(
            core.Paragraph("•  " + core.safe_markup(skill), styles["bullet"])
        )

    def section(title: str) -> None:
        right_content.append(
            core.Paragraph(core.safe_markup(title.upper()), styles["section"])
        )

    def bullet(text: str) -> None:
        right_content.append(
            core.Paragraph("•  " + core.safe_markup(text), styles["bullet"])
        )

    section("Sobre mi")
    right_content.append(
        core.Paragraph(core.safe_markup(draft_data["summary"]), styles["objective"])
    )
    def add_projects():
        if not draft_data.get("projects"):
            return
        section("Proyectos y experiencia práctica")
        for project in draft_data["projects"]:
            right_content.append(core.Paragraph(core.safe_markup(project["title"]), styles["experience"]))
            bullet(core._short_text(project["description"], 300))
            if project.get("technologies"):
                bullet("Tecnologías: " + ", ".join(project["technologies"][:8]))
    if draft_data.get("project_focus"):
        add_projects()
    section("Formación académica")
    right_content.append(
        core.Paragraph("<u>Estudios Académicos</u>", styles["subheading"])
    )
    for item in draft_data["education"]:
        bullet(f"{item['institution']} ({item['title']})")
    right_content.append(
        core.Paragraph("<u>Cursos Realizados</u>", styles["subheading"])
    )
    for item in draft_data["courses"]:
        bullet(f"{item['title']} — {item['institution']}")
    if draft_data["experiences"]:
        section(draft_data.get("experience_heading", "Experiencia laboral"))
    for experience in draft_data["experiences"]:
        right_content.append(
            core.Paragraph(
                core.safe_markup(
                    f"{experience['title']}: {experience['employer']}"
                ),
                styles["experience"],
            )
        )
        for responsibility in experience["selected_responsibilities"]:
            if isinstance(responsibility, dict):
                bullet(
                    f"{responsibility['employer']}: {responsibility['text']}"
                )
            else:
                bullet(responsibility)
    if not draft_data.get("project_focus"):
        add_projects()
    if draft_data["references"]:
        section("Referencias personales")
        reference_rows = []
        references = draft_data["references"]
        for start in range(0, len(references), 2):
            row = []
            for item in references[start : start + 2]:
                row.append(
                    core.Paragraph(
                        core.safe_markup(
                            f"•  {item['name']}\n({item['role']})"
                            f"\nCel. {item['phone']}"
                        ),
                        styles["reference"],
                    )
                )
            if len(row) == 1:
                row.append("")
            reference_rows.append(row)
        reference_table = core.Table(
            reference_rows,
            colWidths=[68 * core.mm, 68 * core.mm],
            hAlign="LEFT",
        )
        reference_table.setStyle(
            core.TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3 * core.mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        right_content.append(reference_table)
    layout = core.Table(
        [[left_content, right_content]],
        colWidths=[42 * core.mm, 144 * core.mm],
        hAlign="LEFT",
    )
    layout.setStyle(
        core.TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), sidebar),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (0, 0), 3 * core.mm),
                ("RIGHTPADDING", (0, 0), (0, 0), 3 * core.mm),
                ("LEFTPADDING", (1, 0), (1, 0), 5 * core.mm),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * core.mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    document = core.SimpleDocTemplate(
        output,
        pagesize=core.A4,
        rightMargin=12 * core.mm,
        leftMargin=12 * core.mm,
        topMargin=8 * core.mm,
        bottomMargin=8 * core.mm,
        title=f"{candidate['name']} - {draft_data['position']}",
        author=candidate["name"],
    )
    document.build([layout])
    output.seek(0)
    return output
