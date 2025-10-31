# Versión FINAL OPTIMIZADA - Usando caché granular
import streamlit as st
from backend.db import init_tables, ensure_db
from backend.services import (
    get_asignaturas_por_periodo,
    get_secciones_de_asignatura,
    inscribir_en_seccion,
    mis_inscripciones,        
    cancelar_inscripcion, 
)
from langchain_groq import ChatGroq
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
import os

# --- CONSTANTES ---
PDF_PATH = "reglamento.pdf"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "llama-3.1-8b-instant"

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Chatbot Académico Duoc UC", page_icon="🤖", layout="wide")
st.title("🤖 Chatbot del Reglamento Académico")

# --- CARGA DE LA API KEY DE GROQ ---
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("La clave de API de Groq no está configurada. Por favor, agrégala a los Secrets de Streamlit.")
    st.stop()  # Detiene la ejecución si no hay API key

# ⚙️ Bootstrap BD (Opción B: creación automática desde el .sql)
ensure_db()     # crea data/duoc_chatbot.db desde data/malla_duoc.sql si no existe
init_tables()   # asegura la tabla 'inscripciones'

# --- SECCIÓN DE FUNCIONES CACHEADAS ---
@st.cache_data(show_spinner="Cargando y procesando el PDF...")
def cargar_y_procesar_pdf(pdf_path):
    loader = PyPDFLoader(pdf_path)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    docs = loader.load_and_split(text_splitter=text_splitter)
    return docs

@st.cache_resource(show_spinner="Creando el índice de búsqueda (Retriever)...")
def crear_retriever(_docs):
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vector_store = Chroma.from_documents(_docs, embeddings)
    vector_retriever = vector_store.as_retriever(search_kwargs={"k": 7})
    bm25_retriever = BM25Retriever.from_documents(_docs); bm25_retriever.k = 7
    return EnsembleRetriever(retrievers=[bm25_retriever, vector_retriever], weights=[0.7, 0.3])

@st.cache_resource(show_spinner="Conectando con el modelo de lenguaje...")
def obtener_llm(api_key):
    return ChatGroq(api_key=api_key, model=LLM_MODEL, temperature=0.1)

def crear_cadena_rag(_retriever, _llm):
    prompt_template = """
    INSTRUCCIÓN PRINCIPAL: Responde SIEMPRE en español.
    Eres un asistente experto en el reglamento académico de Duoc UC. Tu objetivo es dar respuestas claras y precisas basadas ÚNICAMENTE en el contexto proporcionado.
    Si la pregunta es general sobre "qué debe saber un alumno nuevo", crea un resumen que cubra los puntos clave: Asistencia, Calificaciones para aprobar, y Causas de Reprobación.

    CONTEXTO:
    {context}

    PREGUNTA:
    {input}

    RESPUESTA:
    """
    prompt = ChatPromptTemplate.from_template(prompt_template)
    document_chain = create_stuff_documents_chain(_llm, prompt)
    return create_retrieval_chain(_retriever, document_chain)

# --- LÓGICA DE LA APLICACIÓN ---
try:
    # 1. Cargar y procesar documentos
    docs = cargar_y_procesar_pdf(PDF_PATH)

    # 2. Crear el retriever
    retriever = crear_retriever(docs)

    # 3. Obtener el LLM
    llm = obtener_llm(GROQ_API_KEY)

    # 4. Crear la cadena RAG
    retrieval_chain = crear_cadena_rag(retriever, llm)

    # ====== TABS ======
    tab_chat, tab_ins = st.tabs(["💬 Chat Reglamento", "📝 Inscripción"])

    # ====== TAB 1: Chat Reglamento ======
    with tab_chat:
        st.subheader("Asistente del Reglamento Académico")

        if "messages" not in st.session_state:
            st.session_state.messages = []

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("¿Qué duda tienes sobre el reglamento?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Pensando... 💭"):
                    response = retrieval_chain.invoke({"input": prompt})
                    st.markdown(response["answer"])
            st.session_state.messages.append({"role": "assistant", "content": response["answer"]})

    # ====== TAB 2: Inscripción ======
    with tab_ins:
        st.subheader("Inscripción (demo funcional)")

        # Identidad simple (en prod: autenticar)
        rut_demo = st.text_input("RUT alumno (demo)", value="12345678-9")

        col1, col2 = st.columns(2)
        with col1:
            periodo_sel = st.number_input("Periodo", min_value=1, max_value=8, value=3, step=1)
            asigs = get_asignaturas_por_periodo(int(periodo_sel))
            opciones = [f"{a['nombre']} ({a['id_asignatura']})" for a in asigs] or ["(Sin ramos en este periodo)"]
            asignatura_opt = st.selectbox("Asignatura", opciones)
            id_asig_sel = asignatura_opt.split("(")[-1].rstrip(")") if "(" in asignatura_opt else None

        with col2:
            turno_sel = st.selectbox("Turno", ["Todos", "Diurno", "Vespertino"])

        if id_asig_sel:
            secciones = get_secciones_de_asignatura(
                id_asig_sel,
                None if turno_sel == "Todos" else turno_sel
            )
            st.write(f"Secciones de **{id_asig_sel}** ({'todas' if turno_sel=='Todos' else turno_sel}):")

            if not secciones:
                st.info("No hay secciones con ese filtro.")
            else:
                etiquetas = [
                    f"{s['id_seccion']} | {s['profesor']} | {s['horario']} | cupos: {s['cupos_restantes']} | {s['turno']}"
                    for s in secciones
                ]
                idx = st.selectbox("Elige una sección", list(range(len(etiquetas))), format_func=lambda i: etiquetas[i])
                sec_sel = secciones[idx]

                aprobados = st.text_input("Ramos aprobados (códigos separados por coma)", value="")
                aprobados_list = [x.strip() for x in aprobados.split(",")] if aprobados.strip() else []

                if st.button("Inscribirme en esta sección"):
                    res = inscribir_en_seccion(
                        rut_alumno=rut_demo,
                        id_seccion=sec_sel["id_seccion"],
                        ramos_aprobados=aprobados_list
                    )
                    if res.get("ok"):
                        st.success(f"✅ {res['msg']} → {sec_sel['id_seccion']} ({sec_sel['horario']}) con {sec_sel['profesor']}")
                        st.rerun()   # o st.experimental_rerun() si tu Streamlit es antiguo
                    else:
                        st.error(f"❌ {res.get('error','No se pudo inscribir')}")

        # --- Mis inscripciones (listar y cancelar) ---
        st.divider()
        st.markdown("### Mis inscripciones")
        ins = mis_inscripciones(rut_demo)

        if not ins:
            st.info("Aún no tienes inscripciones.")
        else:
            st.dataframe(
                [{"Sección": i["id_seccion"], "Ramo": i["id_asignatura"], "Profesor": i["profesor"], "Horario": i["horario"], "Turno": i["turno"]} for i in ins],
                hide_index=True,
                use_container_width=True,
            )

            opciones_cancel = [f"{i['id_seccion']} · {i['id_asignatura']} · {i['horario']}" for i in ins]
            idx_cancel = st.selectbox(
                "Selecciona una inscripción para cancelar",
                list(range(len(opciones_cancel))),
                format_func=lambda i: opciones_cancel[i]
            )
            sel_cancel = ins[idx_cancel]

            if st.button("Cancelar inscripción seleccionada", type="secondary"):
                res = cancelar_inscripcion(rut_demo, sel_cancel["id_seccion"])


except Exception as e:
    st.error(f"Ha ocurrido un error durante la ejecución: {e}")
    st.exception(e)  # Muestra el traceback completo en Streamlit



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

