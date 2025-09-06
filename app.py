from io import BytesIO
import csv
from flask import Flask, render_template, request, send_file

# ---------- App ----------
app = Flask(__name__)

# ---------- Roster desde CSV ----------
def load_paddlers():
    """
    Lee paddlers.csv con columnas: nombre,peso
    Devuelve dict {nombre: peso}. Incluye entrada '' -> 0.0
    """
    data = {"": 0.0}
    try:
        with open("paddlers.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("nombre") or "").strip()
                weight = (row.get("peso") or "").strip()
                if name == "":
                    # Permite una fila vacía como opción en el <select>
                    data[""] = 0.0
                    continue
                try:
                    data[name] = float(weight.replace(",", "."))
                except ValueError:
                    # Si hay un valor mal escrito en CSV, se ignora esa fila
                    continue
    except FileNotFoundError:
        pass
    return data

PADDLERS = load_paddlers()

# ---------- Definición de botes ----------
LAYOUTS = {10: {"benches": 5}, 20: {"benches": 10}}

# ---------- Lógica de balance ----------
def compute_balance(boat_size: int, seat_names: dict, drummer_w: float, helm_w: float):
    benches = LAYOUTS[boat_size]["benches"]
    left_w, right_w = [], []
    assignments = []

    for i in range(1, benches + 1):
        l_name = seat_names.get(f"L{i}", "") or ""
        r_name = seat_names.get(f"R{i}", "") or ""
        lw = float(PADDLERS.get(l_name, 0.0))
        rw = float(PADDLERS.get(r_name, 0.0))
        left_w.append(lw)
        right_w.append(rw)
        assignments.append({
            "bench": i,
            "L_name": l_name, "L_w": lw,
            "R_name": r_name, "R_w": rw
        })

    total_left = sum(left_w)
    total_right = sum(right_w)
    total_all = total_left + total_right + drummer_w + helm_w

    # Proa/Popa: tambor adelante, timón atrás; mitad de bancas para cada zona
    half = benches // 2
    bow_w = drummer_w + sum(left_w[:half]) + sum(right_w[:half])
    stern_w = helm_w + sum(left_w[half:]) + sum(right_w[half:])

    def pct(a, b):
        return round((a / b * 100.0) if b > 0 else 0.0, 2)

    return {
        "assignments": assignments,
        "totals": {
            "left": total_left, "right": total_right,
            "bow": bow_w, "stern": stern_w,
            "total": total_all, "drummer": drummer_w, "helm": helm_w
        },
        "percents": {
            "left": pct(total_left, total_left + total_right),
            "right": pct(total_right, total_left + total_right),
            "bow": pct(bow_w, bow_w + stern_w),
            "stern": pct(stern_w, bow_w + stern_w)
        }
    }

# ---------- PDF ----------
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

def make_pdf(result, benches, drummer, helm, boat_size):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Balance Barco Dragón")
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Balance de Pesos — Barco Dragón", styles["Title"]))
    story.append(Paragraph(f"Barco: DB{boat_size} · Bancas: {benches}", styles["Normal"]))
    story.append(Paragraph(
        f"Tambor: {drummer} ({result['totals']['drummer']:.1f} kg) · "
        f"Timón: {helm} ({result['totals']['helm']:.1f} kg)", styles["Normal"]))
    story.append(Spacer(1, 10))

    data_tot = [
        ["Babor (kg)", "Estribor (kg)", "Proa (kg)", "Popa (kg)", "Total (kg)"],
        [f"{result['totals']['left']:.1f}", f"{result['totals']['right']:.1f}",
         f"{result['totals']['bow']:.1f}", f"{result['totals']['stern']:.1f}",
         f"{result['totals']['total']:.1f}"]
    ]
    t1 = Table(data_tot, hAlign='LEFT')
    t1.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
        ('GRID',(0,0),(-1,-1),0.5,colors.grey),
        ('FONT',(0,0),(-1,0),'Helvetica-Bold')
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    data_ass = [["Banca","Babor (Nombre/Peso)","Estribor (Nombre/Peso)"]]
    for row in result["assignments"]:
        ltxt = row['L_name'] or '-'
        if row['L_name']: ltxt += f" ({row['L_w']:.1f} kg)"
        rtxt = row['R_name'] or '-'
        if row['R_name']: rtxt += f" ({row['R_w']:.1f} kg)"
        data_ass.append([row["bench"], ltxt, rtxt])

    t2 = Table(data_ass, hAlign='LEFT', colWidths=[40, 230, 230])
    t2.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
        ('GRID',(0,0),(-1,-1),0.5,colors.grey)
    ]))
    story.append(t2)

    doc.build(story)
    buf.seek(0)
    return buf

# ---------- Rutas ----------
@app.route("/", methods=["GET", "POST"])
def index():
    # Tamaño de bote
    boat_size = int(request.form.get("boat_size") or request.args.get("boat_size") or 10)
    benches = LAYOUTS[boat_size]["benches"]

    # Nombres de tambor/timón (pueden llegar vacíos en GET)
    drummer = request.form.get("drummer", "")
    helm = request.form.get("helm", "")

    # Asientos (nombres)
    seat_names = {f"L{i}": request.form.get(f"L{i}", "") for i in range(1, benches + 1)}
    seat_names.update({f"R{i}": request.form.get(f"R{i}", "") for i in range(1, benches + 1)})

    result = None
    if request.method == "POST":
        d_w = PADDLERS.get(drummer, 0.0)
        h_w = PADDLERS.get(helm, 0.0)
        result = compute_balance(boat_size, seat_names, d_w, h_w)

        # Exportar PDF si el botón fue "Exportar PDF"
        if request.form.get("action") == "pdf":
            pdf = make_pdf(result, benches, drummer, helm, boat_size)
            return send_file(pdf, mimetype="application/pdf",
                             as_attachment=True, download_name="balance_dragonboat.pdf")

    return render_template("index.html",
                           boat_size=boat_size, benches=benches,
                           drummer=drummer, helm=helm,
                           weights=seat_names,
                           paddlers=PADDLERS,
                           result=result)

# ---------- Main ----------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
