# Versión FINAL OPTIMIZADA - Usando caché granular
import streamlit as st
from backend.db import init_tables, ensure_db
from backend.services import (
    get_asignaturas_por_periodo,
    get_secciones_de_asignatura,
    inscribir_en_seccion
)
from langchain_groq import ChatGroq
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.retrievers import BM25Retriever
# --- Importación Estándar para EnsembleRetriever (para versión 0.1.x) ---
from langchain.retrievers import EnsembleRetriever
# --- Fin ---
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
# Se obtiene una sola vez y se pasa a las funciones que la necesiten.
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("La clave de API de Groq no está configurada. Por favor, agrégala a los Secrets de Streamlit.")
    st.stop() # Detiene la ejecución si no hay API key

init_tables()    
# --- SECCIÓN DE FUNCIONES CACHEADAS ---

@st.cache_data(show_spinner="Cargando y procesando el PDF...")
def cargar_y_procesar_pdf(pdf_path):
    """
    Carga el PDF y lo divide en documentos (chunks).
    Usamos @st.cache_data porque los "docs" son datos serializables.
    Esta función solo se ejecutará si el archivo PDF cambia.
    """
    loader = PyPDFLoader(pdf_path)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    docs = loader.load_and_split(text_splitter=text_splitter)
    return docs

@st.cache_resource(show_spinner="Creando el índice de búsqueda (Retriever)...")
def crear_retriever(_docs):
    """
    Crea el ensemble retriever.
    Usamos @st.cache_resource porque carga el modelo de embeddings
    y construye los índices (Chroma y BM25), que son "recursos" complejos.
    Esta función depende de los 'docs' de la función anterior.
    """
    # 1. Modelo de Embeddings
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    
    # 2. Vector Store (Chroma)
    vector_store = Chroma.from_documents(_docs, embeddings)
    vector_retriever = vector_store.as_retriever(search_kwargs={"k": 7})
    
    # 3. Retriever BM25
    bm25_retriever = BM25Retriever.from_documents(_docs)
    bm25_retriever.k = 7
    
    # 4. Ensamble de ambos
    retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever], 
        weights=[0.7, 0.3]
    )
    return retriever

@st.cache_resource(show_spinner="Conectando con el modelo de lenguaje...")
def obtener_llm(api_key):
    """
    Inicializa el modelo de lenguaje (LLM) de Groq.
    Usamos @st.cache_resource porque es un "recurso" (un cliente de API).
    """
    llm = ChatGroq(
        api_key=api_key,
        model=LLM_MODEL,
        temperature=0.1
    )
    return llm

def crear_cadena_rag(_retriever, _llm):
    """
    Crea la cadena RAG final.
    Esta función es muy rápida y no necesita caché.
    Si el prompt cambia, esto se regenera instantáneamente
    sin tener que recargar el PDF o los modelos.
    """
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
    retrieval_chain = create_retrieval_chain(_retriever, document_chain)
    return retrieval_chain

# --- LÓGICA DE LA APLICACIÓN DE CHAT ---
try:
    # 1. Cargar y procesar documentos (se cachea con @st.cache_data)
    docs = cargar_y_procesar_pdf(PDF_PATH)
    
    # 2. Crear el retriever (se cachea con @st.cache_resource)
    retriever = crear_retriever(docs)
    
    # 3. Obtener el LLM (se cachea con @st.cache_resource)
    llm = obtener_llm(GROQ_API_KEY)
    
    # 4. Crear la cadena RAG (esto es rápido, no requiere caché)
    retrieval_chain = crear_cadena_rag(retriever, llm)

    # --- Interfaz de Chat ---
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

except Exception as e:
    st.error(f"Ha ocurrido un error durante la ejecución: {e}")

    st.exception(e) # Muestra el traceback completo en Streamlit
