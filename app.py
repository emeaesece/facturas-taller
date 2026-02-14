import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Taller Pro Cloud 2026", page_icon="🔧", layout="wide")

# Estilo para botones y tablas elásticas
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3.5em; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# Inicialización de IA forzando Versión v1 (Evita el error 404)
try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    client_ia = genai.Client(
        api_key=api_key_env,
        http_options={'api_version': 'v1'} # Ruta de producción estable
    )
except Exception as e:
    st.error("❌ Error: No se encontró GOOGLE_API_KEY en Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. MOTOR DE BASE DE DATOS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error Sheets: {e}")
        return None

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        for row in ws.get_all_records():
            if str(row['username']) == str(u) and str(row['password']) == str(p):
                return True
        return False
    except: return False

# ==========================================
# 🧠 3. MOTOR IA Y LIMPIEZA DE NÚMEROS
# ==========================================
def limpiar_monto_py(valor):
    """Maneja formatos como 1.500.000 o 1.500,50"""
    if not valor: return 0.0
    try:
        s = str(valor).upper().replace('GS', '').replace('$', '').strip()
        # Si hay puntos y comas (1.234,56), quitamos puntos y cambiamos coma por punto
        if '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        # Si solo hay puntos (1.500.000), los quitamos
        elif '.' in s and ',' not in s:
            # Caso especial: ¿es decimal (1.50) o miles (1.500)? 
            # Si hay 3 dígitos después del punto, es miles.
            partes = s.split('.')
            if len(partes[-1]) == 3: s = s.replace('.', '')
        # Si solo hay coma (1500,50), la cambiamos por punto
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def analizar_factura(archivo_bytes, mime_type):
    # Prompt reforzado
    prompt = """Analiza esta factura. Extrae un JSON con: 
    {
      "fecha": "YYYY-MM-DD", 
      "proveedor": "Nombre", 
      "items": [{"producto": "desc", "cantidad": 1, "unitario": 0, "total": 0}]
    }
    Devuelve SOLO el JSON sin texto extra."""
    
    try:
        # Usamos la sintaxis más compatible para evitar el error 400
        response = client_ia.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)
            ]
        )
        # Limpieza manual de la respuesta (más seguro que forzarlo en config)
        res_text = response.text.strip()
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0]
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0]
            
        return json.loads(res_text)
    except Exception as e:
        st.error(f"Error en comunicación con IA: {e}")
        return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
# ==========================================
if 'sesion' not in st.session_state: st.session_state.sesion = False

if not st.session_state.sesion:
    st.title("🔐 Acceso Taller Cloud")
    col1, col2 = st.columns(2)
    u = col1.text_input("Usuario")
    p = col2.text_input("Contraseña", type="password")
    if st.button("Ingresar", type="primary", width='stretch'):
        if check_login(u, p):
            st.session_state.sesion = True
            st.session_state.user = u
            st.rerun()
        else: st.error("Acceso denegado.")
else:
    with st.sidebar:
        st.header(f"🔧 {st.session_state.user}")
        opc = st.radio("Menú", ["📥 Cargar Compra", "📊 Ver Historial", "🚀 Salir"])

    if opc == "📥 Cargar Compra":
        st.title("📥 Registro de Facturas")
        f = st.file_uploader("Subir PDF o Imagen", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("Analizar y Guardar", type="primary", width='stretch'):
            with st.spinner("🤖 Procesando documento..."):
                datos = analizar_factura(f.getvalue(), f.type)
                if datos and "items" in datos:
                    st.write("### Datos extraídos:")
                    st.json(datos)
                    
                    sh = conectar_sheets()
                    ws = sh.worksheet("Gastos")
                    count = 0
                    
                    for i in datos["items"]:
                        # Aplicar limpieza de números de Paraguay
                        c = limpiar_monto_py(i.get("cantidad", 1))
                        u_p = limpiar_monto_py(i.get("unitario", 0))
                        t = limpiar_monto_py(i.get("total", 0))
                        
                        ws.append_row([
                            datos.get("fecha", ""),
                            datos.get("proveedor", ""),
                            i.get("producto", ""),
                            c, "u", u_p, t,
                            st.session_state.user,
                            str(datetime.datetime.now())
                        ])
                        count += 1
                    st.success(f"✅ Se guardaron {count} items en la nube.")
                else:
                    st.error("No se detectaron items. Revisa que el archivo sea legible.")

    elif opc == "📊 Ver Historial":
        st.title("📊 Base de Datos")
        try:
            sh = conectar_sheets()
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            st.dataframe(df, width='stretch')
        except: st.info("No hay datos cargados.")
        
    if opc == "🚀 Salir":
        st.session_state.sesion = False
        st.rerun()
