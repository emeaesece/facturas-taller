import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS (2026 READY)
# ==========================================

st.set_page_config(
    page_title="Taller Pro Cloud", 
    page_icon="🔧", 
    layout="wide"
)

# Estilos para facilitar el uso en pantallas táctiles y móviles
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3.5em; font-weight: bold; }
    .stDataFrame { border: 1px solid #f0f2f6; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# Recuperar API Key desde Secrets de Streamlit
try:
    GEMINI_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    GEMINI_KEY = "PEGA_TU_CLAVE_AQUI_SOLO_SI_ES_LOCAL"

genai.configure(api_key=GEMINI_KEY)

# ==========================================
# ☁️ 2. MOTOR DE BASE DE DATOS (GOOGLE SHEETS)
# ==========================================

def conectar_sheets():
    """Conexión segura con Google Sheets usando Service Account"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        # Limpieza de clave privada para evitar errores de formato
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # Nombre del archivo en Google Drive
        return client.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error crítico de conexión: {e}")
        return None

def check_login(u, p):
    """Valida usuario contra la pestaña 'Usuarios'"""
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        records = ws.get_all_records()
        for row in records:
            if str(row['username']) == str(u) and str(row['password']) == str(p):
                return True
        return False
    except:
        return False

def guardar_en_nube(item, usuario):
    """Guarda cada ítem en la pestaña 'Gastos'"""
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Gastos")
        fila = [
            item['Fecha'], 
            item['Proveedor'], 
            item['Producto'], 
            item['Cantidad'], 
            item['Unidad'], 
            item['Precio Unitario'], 
            item['Precio Total'], 
            usuario, 
            str(datetime.datetime.now())
        ]
        ws.append_row(fila)
        return True
    except:
        return False

# ==========================================
# 🧠 3. MOTOR DE INTELIGENCIA ARTIFICIAL Y LIMPIEZA
# ==========================================

def limpiar_numero(valor):
    """Transforma textos como '1.500,50' o '1500.50' en números reales (float)"""
    if isinstance(valor, (int, float)): return float(valor)
    if not valor: return 0.0
    try:
        # Quitamos símbolos de moneda y espacios
        t = str(valor).strip().lower().replace('gs', '').replace('$', '').replace(' ', '')
        # Caso: 1.500,00 -> 1500.00
        if '.' in t and ',' in t:
            t = t.replace('.', '').replace(',', '.')
        # Caso: 1500,00 -> 1500.00
        elif ',' in t:
            t = t.replace(',', '.')
        return float(t)
    except:
        return 0.0

def analizar_con_ia(archivo_bytes, mime_type):
    """Envía factura a Gemini y recupera JSON estructurado"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = """
    Analiza esta factura de taller mecánico. Extrae los productos/repuestos comprados.
    
    IMPORTANTE: 
    - Extrae los números exactamente como aparecen (pueden tener puntos o comas).
    - Si no hay cantidad, usa 1.
    - Devuelve ÚNICAMENTE un JSON con esta estructura:
    {
        "fecha": "YYYY-MM-DD",
        "proveedor": "Nombre Empresa",
        "items": [
            {"prod": "descripción", "cant": "valor", "uni": "u", "unit": "valor", "tot": "valor"}
        ]
    }
    """
    try:
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": archivo_bytes}])
        clean_text = response.text.strip().replace("```json", "").replace("```", "")
        # Encontrar el inicio y fin del JSON por si la IA agrega texto extra
        start = clean_text.find("{")
        end = clean_text.rfind("}") + 1
        return json.loads(clean_text[start:end])
    except:
        return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO (LOGIC & UI)
# ==========================================

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    # --- PANTALLA DE ACCESO ---
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Taller Pro Cloud")
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.button("Acceder", type="primary", width='stretch'):
            if check_login(u, p):
                st.session_state.autenticado = True
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Credenciales no válidas.")
else:
    # --- PANTALLA DE TRABAJO ---
    with st.sidebar:
        st.header(f"🔧 Hola, {st.session_state.user}")
        opcion = st.radio("Menú Principal", ["📥 Cargar Facturas", "📊 Historial de Gastos", "🚪 Cerrar Sesión"])
        
        if opcion == "🚪 Cerrar Sesión":
            st.session_state.autenticado = False
            st.rerun()

    # MÓDULO 1: CARGA DE FACTURAS
    if opcion == "📥 Cargar Facturas":
        st.title("📥 Digitalizar Factura")
        st.info("Sube tus facturas (PDF o Imagen). El sistema las procesará y guardará en la nube automáticamente.")
        
        files = st.file_uploader("Seleccionar archivos", accept_multiple_files=True)
        
        if files and st.button("Procesar y Guardar", type="primary", width='stretch'):
            progreso = st.progress(0)
            status = st.empty()
            contador_final = 0
            
            for i, f in enumerate(files):
                progreso.progress((i + 1) / len(files))
                status.write(f"🔍 Analizando: {f.name}...")
                
                datos_ia = analizar_con_ia(f.getvalue(), f.type)
                
                if datos_ia and "items" in datos_ia:
                    fecha_f = datos_ia.get("fecha", str(datetime.date.today()))
                    prov_f = datos_ia.get("proveedor", "Desconocido")
                    
                    for item in datos_ia["items"]:
                        # Limpieza de números para manejar puntos/comas latinos
                        c_limpia = limpiar_numero(item.get("cant", 1))
                        u_limpia = limpiar_numero(item.get("unit", 0))
                        t_limpio = limpiar_numero(item.get("tot", 0))
                        
                        # Re-cálculo de seguridad si el total viene en 0
                        if t_limpio == 0 and u_limpia > 0:
                            t_limpio = c_limpia * u_limpia
                        
                        registro = {
                            "Fecha": fecha_f,
                            "Proveedor": prov_f,
                            "Producto": item.get("prod", "Sin nombre"),
                            "Cantidad": c_limpia,
                            "Unidad": item.get("uni", "u"),
                            "Precio Unitario": u_limpia,
                            "Precio Total": t_limpio
                        }
                        
                        if guardar_en_nube(registro, st.session_state.user):
                            contador_final += 1
                time.sleep(1) # Pequeña pausa para no saturar la API
            
            status.empty()
            if contador_final > 0:
                st.success(f"✅ ¡Éxito! Se han registrado {contador_final} ítems en Google Sheets.")
            else:
                st.error("❌ No se detectaron ítems. Verifica que el archivo sea legible.")

    # MÓDULO 2: CONSULTA DE HISTORIAL
    elif opcion == "📊 Historial de Gastos":
        st.title("📊 Base de Datos Histórica")
        busqueda = st.text_input("🔍 Buscar por producto, proveedor o fecha...")
        
        try:
            sh = conectar_sheets()
            ws = sh.worksheet("Gastos")
            df = pd.DataFrame(ws.get_all_records())
            
            if not df.empty:
                if busqueda:
                    # Filtro inteligente en todas las columnas
                    mask = df.apply(lambda r: r.astype(str).str.contains(busqueda, case=False).any(), axis=1)
                    df = df[mask]
                
                st.dataframe(
                    df, 
                    column_config={
                        "Precio Total": st.column_config.NumberColumn(format="$ %.2f"),
                        "Precio Unitario": st.column_config.NumberColumn(format="$ %.2f"),
                        "Cantidad": st.column_config.NumberColumn(format="%.2f")
                    },
                    width='stretch'
                )
            else:
                st.warning("Aún no hay datos registrados.")
        except Exception as e:
            st.error(f"No se pudo cargar el historial: {e}")
