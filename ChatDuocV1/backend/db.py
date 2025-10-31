# backend/db.py
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "duoc_chatbot.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_tables():
    """Crea tabla de inscripciones si no existe (el resto viene del .sql)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inscripciones (
        rut_alumno TEXT NOT NULL,
        id_seccion TEXT NOT NULL,
        PRIMARY KEY (rut_alumno, id_seccion),
        FOREIGN KEY (id_seccion) REFERENCES secciones(id_seccion)
    );
    """)
    conn.commit()
    conn.close()
