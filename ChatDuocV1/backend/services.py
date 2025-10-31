# backend/services.py
from .db import get_connection
import re

DAYS = {"Lunes":"Lun","Martes":"Mar","Miércoles":"Mie","Jueves":"Jue","Viernes":"Vie","Sábado":"Sab","Domingo":"Dom"}

def _time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":"); return int(h)*60 + int(m)

def _parse_horario(horario_str: str):
    m = re.match(r"(.+?)\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", horario_str)
    if not m: return []
    dias_raw, ini_raw, fin_raw = m.group(1), m.group(2), m.group(3)
    ini, fin = _time_to_minutes(ini_raw), _time_to_minutes(fin_raw)
    dias = [x.strip() for x in dias_raw.split("y")]
    return [{"dia": DAYS.get(d, d), "ini": ini, "fin": fin} for d in dias]

def _horarios_chocan(a, b):
    for x in a:
        for y in b:
            if x["dia"] == y["dia"] and x["ini"] < y["fin"] and y["ini"] < x["fin"]:
                return True
    return False

# -------- Lecturas --------
def get_asignaturas():
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT id_asignatura, nombre, periodo FROM asignaturas ORDER BY periodo, nombre;""")
    out = [dict(r) for r in cur.fetchall()]; conn.close(); return out

def get_asignaturas_por_periodo(periodo: int):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT id_asignatura, nombre, periodo FROM asignaturas WHERE periodo=? ORDER BY nombre;""",(periodo,))
    out = [dict(r) for r in cur.fetchall()]; conn.close(); return out

def buscar_id_por_nombre(nombre: str):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT id_asignatura, nombre FROM asignaturas WHERE lower(nombre)=lower(?) LIMIT 1;""",(nombre,))
    row = cur.fetchone()
    if not row:
        cur.execute("""SELECT id_asignatura, nombre FROM asignaturas WHERE lower(nombre) LIKE lower(?) LIMIT 1;""",(f"%{nombre}%",))
        row = cur.fetchone()
    conn.close(); return dict(row) if row else None

def get_secciones_de_asignatura(id_asignatura: str, turno: str|None=None):
    conn = get_connection(); cur = conn.cursor()
    if turno:
        cur.execute("""SELECT id_seccion, profesor, cupos_restantes, horario, turno
                       FROM secciones WHERE id_asignatura=? AND turno=? ORDER BY horario;""",(id_asignatura, turno))
    else:
        cur.execute("""SELECT id_seccion, profesor, cupos_restantes, horario, turno
                       FROM secciones WHERE id_asignatura=? ORDER BY turno, horario;""",(id_asignatura,))
    out = [dict(r) for r in cur.fetchall()]; conn.close(); return out

def get_prerrequisitos_faltantes(id_asignatura: str, ramos_aprobados: list[str]):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT id_requisito FROM prerrequisitos WHERE id_asignatura=?;""",(id_asignatura,))
    reqs = [r["id_requisito"] for r in cur.fetchall()]; conn.close()
    return [r for r in reqs if r not in ramos_aprobados]

def _get_secciones_actuales_del_alumno(rut_alumno: str):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT s.id_seccion, s.id_asignatura, s.horario
                   FROM inscripciones i JOIN secciones s ON i.id_seccion=s.id_seccion
                   WHERE i.rut_alumno=?;""",(rut_alumno,))
    rows = [dict(r) for r in cur.fetchall()]; conn.close()
    for r in rows: r["bloques"] = _parse_horario(r["horario"])
    return rows

def hay_choque_con_horario(rut_alumno: str, id_seccion_nueva: str):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT id_seccion, id_asignatura, horario FROM secciones WHERE id_seccion=?;""",(id_seccion_nueva,))
    row = cur.fetchone(); conn.close()
    if not row: return (True, "La sección no existe")
    nueva = {"id_seccion": row["id_seccion"], "id_asignatura": row["id_asignatura"],
             "horario": row["horario"], "bloques": _parse_horario(row["horario"])}
    actuales = _get_secciones_actuales_del_alumno(rut_alumno)
    for s in actuales:
        if _horarios_chocan(nueva["bloques"], s["bloques"]):
            return (True, f"Choca con {s['id_seccion']} ({s['horario']})")
    return (False, None)

# -------- Transacción principal --------
def inscribir_en_seccion(rut_alumno: str, id_seccion: str, ramos_aprobados: list[str]):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT cupos_restantes, id_asignatura FROM secciones WHERE id_seccion=?;""",(id_seccion,))
    row = cur.fetchone()
    if not row: conn.close(); return {"ok": False, "error": "Sección no existe"}
    if row["cupos_restantes"] <= 0: conn.close(); return {"ok": False, "error": "No quedan cupos"}
    id_asig = row["id_asignatura"]

    cur.execute("""SELECT s.id_seccion FROM inscripciones i
                   JOIN secciones s ON i.id_seccion=s.id_seccion
                   WHERE i.rut_alumno=? AND s.id_asignatura=?;""",(rut_alumno, id_asig))
    if cur.fetchone(): conn.close(); return {"ok": False, "error": "Ya estás inscrito en otra sección de este ramo"}

    faltantes = get_prerrequisitos_faltantes(id_asig, ramos_aprobados)
    if faltantes: conn.close(); return {"ok": False, "error": f"No cumples prerrequisitos: {', '.join(faltantes)}"}

    choca, det = hay_choque_con_horario(rut_alumno, id_seccion)
    if choca: conn.close(); return {"ok": False, "error": f"Choque de horario: {det}"}

    cur.execute("""INSERT INTO inscripciones (rut_alumno, id_seccion) VALUES (?,?);""",(rut_alumno, id_seccion))
    cur.execute("""UPDATE secciones SET cupos_restantes=cupos_restantes-1 WHERE id_seccion=?;""",(id_seccion,))
    conn.commit(); conn.close()
    return {"ok": True, "msg": "Inscripción exitosa"}

# backend/services.py (al final)

def mis_inscripciones(rut_alumno: str):
    """
    Retorna la lista de secciones en las que el alumno está inscrito.
    """
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT s.id_seccion, s.id_asignatura, s.profesor, s.horario, s.turno
        FROM inscripciones i
        JOIN secciones s ON i.id_seccion = s.id_seccion
        WHERE i.rut_alumno = ?
        ORDER BY s.id_asignatura, s.id_seccion;
    """, (rut_alumno,))
    out = [dict(r) for r in cur.fetchall()]
    conn.close()
    return out


def cancelar_inscripcion(rut_alumno: str, id_seccion: str):
    """
    Elimina la inscripción del alumno en la sección y devuelve el cupo.
    """
    conn = get_connection(); cur = conn.cursor()

    # Verifica que exista la inscripción
    cur.execute(
        "SELECT 1 FROM inscripciones WHERE rut_alumno=? AND id_seccion=?;",
        (rut_alumno, id_seccion),
    )
    if not cur.fetchone():
        conn.close()
        return {"ok": False, "error": "No estás inscrito en esa sección"}

    try:
        # Borra inscripción y devuelve cupo (operación atómica)
        cur.execute(
            "DELETE FROM inscripciones WHERE rut_alumno=? AND id_seccion=?;",
            (rut_alumno, id_seccion),
        )
        cur.execute(
            "UPDATE secciones SET cupos_restantes = cupos_restantes + 1 WHERE id_seccion=?;",
            (id_seccion,),
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()
