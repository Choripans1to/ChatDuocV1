# backend/db.py
import sqlite3
from pathlib import Path

# Rutas de la BD y del seed SQL
DB_PATH  = Path(__file__).resolve().parent.parent / "data" / "duoc_chatbot.db"
SQL_SEED = Path(__file__).resolve().parent.parent / "data" / "malla_duoc.sql"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  
    return conn


def ensure_db():
    """
    Si NO existe la BD y SÍ existe el seed SQL, crea data/duoc_chatbot.db
    ejecutando data/malla_duoc.sql.
    """
    if not DB_PATH.exists() and SQL_SEED.exists():
        con = sqlite3.connect(DB_PATH)
        con.executescript(SQL_SEED.read_text(encoding="utf-8"))
        con.commit()
        con.close()

def init_tables():
    """
    Crea tabla auxiliar que no viene en el seed (p. ej. 'inscripciones').
    Llama a ensure_db() ANTES (desde app.py) para garantizar que la BD exista.
    """
    con = get_connection()
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inscripciones (
        rut_alumno   TEXT NOT NULL,
        id_seccion   TEXT NOT NULL,
        PRIMARY KEY (rut_alumno, id_seccion),
        FOREIGN KEY (id_seccion) REFERENCES secciones(id_seccion)
    );
    """)
    con.commit()
    con.close()
