"""
RTS Vendor Feasibility Report — auto-fill + PDF generation
============================================================
Fills the "Residential Roof Top Solar Installation — Vendor Feasibility
Report Format" template with a project's data and renders it to PDF.
Only the text fields listed below are touched; every other line
(OEM/EPC/bank details, the Site Layout Images field, the whole EHS
checklist on later pages) is left exactly as in the source template,
so the page count and layout never change.

SETUP (one time):
1. Put `RTS_vendor_feasibility_template.docx` (the blank form you gave me)
   in a folder your app can read, e.g.:
       <your app folder>/form_templates/RTS_vendor_feasibility_template.docx
   Update RTS_TEMPLATE_PATH below to match.

2. Your server needs LibreOffice installed for the docx -> pdf step
   (the rest of your app uses reportlab, which can't render a filled
   Word template, so this one route needs `soffice`):
       sudo apt-get install -y libreoffice-writer
   soffice must be on PATH (or set LIBREOFFICE_BIN env var below).

3. `pip install python-docx`.

4. Copy the Flask routes from README_rts_feasibility.md into app.py.
   Copy rts_feasibility_form.html and rts_feasibility_preview.html into
   your templates/ folder. Add the button snippet to project_detail.html.
"""
import os
import shutil
import subprocess
import tempfile
import uuid

from docx import Document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RTS_TEMPLATE_PATH = os.path.join(BASE_DIR, 'form_templates', 'RTS_vendor_feasibility_template.docx')
LIBREOFFICE_BIN = os.environ.get('LIBREOFFICE_BIN', '/usr/bin/soffice')

# Paragraph indices in the template — these correspond 1:1 to the
# numbered items on page 1 of the form. If you ever re-save the .docx
# from Word and the layout shifts, run `python rts_feasibility.py`
# (the self-check at the bottom of this file) to confirm these still
# line up before trusting the output.
P_NAME               = 1   # 1.  Name of the Consumer
P_DISCOM_CONSUMER_ID = 2   # 2.  Discom Consumer ID
P_DISCOM_ID          = 3   # 3.  Discom ID
P_SURYA_GHAR_ID      = 4   # 4.  PM Surya Shakti Portal ID
P_JAN_SAMARTH_ID     = 5   # 5.  Jan Samarth ID
P_ADDRESS            = 6   # 6.  Address for Installation
P_DISTRICT           = 7   # 7.  District of Installation
# 8.  State of Installation — already hard-coded "KERALA" in the template, untouched
P_PINCODE            = 10  # 9.  Pin Code of Installation
# 10. OEM Name — already hard-coded "UTL SOLAR", untouched
P_CHANNEL_PARTNER    = 15  # 11. Channel Partner, if any
# 12-15 — EPC contractor name/address/register ID/bank details are all
# fixed vendor details already baked into the template; never touched.
P_RTS_APPLIED_KW     = 24  # 16. RTS Capacity in KW Applied
P_RTS_INSTALLED_KW   = 25  # 17. Actual RTS Capacity to be installed
P_PROJECT_COST       = 30  # 20. Project Cost (all inclusive)
# 21. Site Layout Images (paragraph 32) — deliberately never touched.


def _append(paragraph, value):
    """Add the value as a new run at the end of the paragraph, right
    after the printed label, matching how the template is laid out."""
    if value in (None, ''):
        return
    paragraph.add_run(str(value))


def build_rts_feasibility_docx(
    project,
    jan_samarth_id,
    rts_capacity_applied_kw,
    project_cost,
    discom_id='',
    channel_partner='',
    output_dir='/tmp',
):
    """
    Fill the RTS vendor feasibility template for `project` (a Project
    ORM instance) and save the filled .docx. Field mapping:

      Name of the Consumer          -> project.customer.name
      Discom Consumer ID            -> project.connection_details.consumer_number
      Discom ID                     -> `discom_id` (not tracked elsewhere — pass in)
      PM Surya Shakti Portal ID     -> project.customer.name (per instruction)
      Jan Samarth ID                -> `jan_samarth_id` (caller resolves the
                                        "same as consumer name?" question before
                                        calling this — see the Flask routes)
      Address for Installation      -> project.customer.full_address
      District of Installation      -> project.customer.district
      State of Installation         -> fixed "KERALA" (already in template)
      Pin Code of Installation      -> project.customer.pincode
      RTS Capacity in KW Applied    -> `rts_capacity_applied_kw`
      Actual RTS Capacity installed -> project.inverter_capacity_kw
      Project Cost (all inclusive)  -> `project_cost`

    Nothing else in the document — including the Site Layout Images
    field and every page after page 1 — is modified. Returns the path
    to the filled .docx.
    """
    doc = Document(RTS_TEMPLATE_PATH)
    paras = doc.paragraphs

    cust = project.customer
    cd = project.connection_details

    _append(paras[P_NAME], cust.name)
    _append(paras[P_DISCOM_CONSUMER_ID], cd.consumer_number if cd else '')
    _append(paras[P_DISCOM_ID], discom_id)
    _append(paras[P_SURYA_GHAR_ID], cust.name)
    _append(paras[P_JAN_SAMARTH_ID], jan_samarth_id)
    _append(paras[P_ADDRESS], cust.full_address or '')
    _append(paras[P_DISTRICT], cust.district or '')
    _append(paras[P_PINCODE], cust.pincode or '')
    _append(paras[P_CHANNEL_PARTNER], channel_partner)
    _append(paras[P_RTS_APPLIED_KW], f'{rts_capacity_applied_kw} kW')
    _append(paras[P_RTS_INSTALLED_KW], f'{project.inverter_capacity_kw} kW')
    _append(paras[P_PROJECT_COST], f'\u20b9{float(project_cost):,.0f}')

    fname = f'RTS_Feasibility_{project.project_code}_{uuid.uuid4().hex[:6]}.docx'
    out_path = os.path.join(output_dir, fname)
    doc.save(out_path)
    return out_path


def convert_docx_to_pdf(docx_path, output_dir='/tmp'):
    """Convert a .docx to .pdf using LibreOffice headless mode."""
    
    libreoffice_bin = os.environ.get(
        'LIBREOFFICE_BIN',
        '/usr/bin/soffice'
    )

    if not os.path.isfile(libreoffice_bin):
        raise RuntimeError(
            f'LibreOffice executable not found at: {libreoffice_bin}'
        )

    with tempfile.TemporaryDirectory() as profile_dir:
        result = subprocess.run(
            [
                libreoffice_bin,
                '--headless',
                '--norestore',
                f'-env:UserInstallation=file://{profile_dir}',
                '--convert-to',
                'pdf',
                '--outdir',
                output_dir,
                docx_path,
            ],
            check=False,
            timeout=60,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(
            'LibreOffice PDF conversion failed.\n'
            f'Exit code: {result.returncode}\n'
            f'STDOUT: {result.stdout}\n'
            f'STDERR: {result.stderr}'
        )

    pdf_path = os.path.splitext(docx_path)[0] + '.pdf'

    if not os.path.isfile(pdf_path):
        raise RuntimeError(
            'LibreOffice ran but did not produce the expected PDF.\n'
            f'STDOUT: {result.stdout}\n'
            f'STDERR: {result.stderr}'
        )

    return pdf_path

def build_rts_feasibility_pdf(project, jan_samarth_id, rts_capacity_applied_kw,
                               project_cost, discom_id='', channel_partner='',
                               output_dir='/tmp'):
    """Convenience wrapper: fill the docx, convert to pdf, return pdf path."""
    docx_path = build_rts_feasibility_docx(
        project, jan_samarth_id, rts_capacity_applied_kw, project_cost,
        discom_id=discom_id, channel_partner=channel_partner,
        output_dir=output_dir,
    )
    pdf_path = convert_docx_to_pdf(docx_path, output_dir)
    os.remove(docx_path)  # only the PDF is needed past this point
    return pdf_path


if __name__ == '__main__':
    # Quick sanity check that the paragraph indices above still match
    # the template — run `python rts_feasibility.py` after replacing
    # the template file to confirm before wiring it into the live app.
    doc = Document(RTS_TEMPLATE_PATH)
    checks = {
        P_NAME: 'Name of the Consumer', P_DISCOM_CONSUMER_ID: 'Discom Consumer ID',
        P_DISCOM_ID: 'Discom ID', P_SURYA_GHAR_ID: 'PM Surya Shakti Portal ID',
        P_JAN_SAMARTH_ID: 'Jan Samarth ID', P_ADDRESS: 'Address for Installation',
        P_DISTRICT: 'District of Installation', P_PINCODE: 'Pin Code of Installation',
        P_CHANNEL_PARTNER: 'Channel Partner', P_RTS_APPLIED_KW: 'RTS Capacity in KW Applied',
        P_RTS_INSTALLED_KW: 'Actual RTS Capacity', P_PROJECT_COST: 'Project Cost',
    }
    ok = True
    for idx, expect in checks.items():
        actual = doc.paragraphs[idx].text
        match = expect.lower() in actual.lower()
        ok = ok and match
        print(('OK  ' if match else 'MISMATCH'), idx, '->', repr(actual))
    print('All indices match template.' if ok else 'FIX INDICES BEFORE USING.')