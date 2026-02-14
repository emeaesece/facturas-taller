import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import json
import time
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import io

# ==========================================
# ⚙️ 1. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Taller Pro Cloud 2026", page_icon="🔧", layout="wide")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3.5em; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 10px; background-color: #28a745; color: white; }
    </style>
    """, unsafe_allow_html=True)

try:
    api_key_env = st.secrets["GOOGLE_API_KEY"]
    # FIX 404: Forzamos explícitamente la versión 'v1' estable
    client_ia = genai.Client(
        api_key=api_key_env,
        http_options={'api_version': 'v1'}
    )
except Exception as e:
    st.error(f"❌ Error de API Key: {e}")
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
        return gspread.authorize(creds).open("BaseDatos_Taller")
    except: return None

# ==========================================
# 🧠 3. MOTOR IA CON MONITOR DE MODELO
# ==========================================
def limpiar_monto_py(valor):
    if not valor: return 0.0
    try:
        s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').replace(',', '.')
        if s.count('.') > 1:
            partes = s.split('.')
            s = "".join(partes[:-1]) + "." + partes[-1]
        return float(s)
    except: return 0.0

def analizar_factura(archivo_bytes, mime_type):
    # Lista de modelos con nombres actualizados para v1 estable
    modelos = ["gemini-1.5-flash", "gemini-1.5-flash-8b"]
    prompt = "Analiza esta factura. Extrae en JSON: fecha (YYYY-MM-DD), proveedor, y items (producto, cantidad, unitario, total). SOLO JSON."
    
    progreso_bar = st.progress(0)
    estado_texto = st.empty()
    
    for idx, mod in enumerate(modelos):
        porcentaje = int(((idx) / len(modelos)) * 100)
        progreso_bar.progress(porcentaje)
        estado_texto.info(f"🤖 Procesando con: **{mod}**...")
        
        try:
            response = client_ia.models.generate_content(
                model=mod,
                contents=[prompt, types.Part.from_bytes(data=archivo_bytes, mime_type=mime_type)]
            )
            txt = response.text.strip()
            if "```json" in txt: txt = txt.split("```json")[1].split("```")[0]
            elif "```" in txt: txt = txt.split("```")[1].split("```")[0]
            
            progreso_bar.progress(100)
            estado_texto.success(f"✅ ¡Motor **{mod}** respondió!")
            time.sleep(1)
            estado_texto.empty()
            progreso_bar.empty()
            return json.loads(txt)
            
        except Exception as e:
            if "404" in str(e) or "429" in str(e):
                continue
            else:
                st.error(f"❌ Error técnico: {e}")
                return None
    
    progreso_bar.empty()
    st.error("❌ Los modelos estables no están respondiendo. Intenta en unos minutos.")
    return None

# ==========================================
# 🖥️ 4. INTERFAZ Y REPORTE
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Taller Pro Cloud")
    u = st.text_input("Usuario")
    p = st.text_input("Pass", type="password")
    if st.button("Entrar"):
        st.session_state.auth = True
        st.session_state.user = u
        st.rerun()
else:
    menu = st.sidebar.radio("Navegación", ["📥 Cargar Compra", "📊 Historial", "📅 Reporte Mensual", "🚀 Salir"])

    if menu == "📥 Cargar Compra":
        st.title("📥 Digitalizar Factura")
        f = st.file_uploader("Sube PDF o Imagen", type=["pdf", "png", "jpg"])
        if f and st.button("Procesar Factura"):
            datos = analizar_factura(f.getvalue(), f.type)
            if datos:
                sh = conectar_sheets()
                if sh:
                    ws = sh.worksheet("Gastos")
                    with st.status("📝 Guardando en la nube...") as s:
                        for i in datos.get("items", []):
                            ws.append_row([
                                datos.get("fecha", ""), datos.get("proveedor", ""),
                                i.get("producto", ""), limpiar_monto_py(i.get("cantidad")),
                                "u", limpiar_monto_py(i.get("unitario")), limpiar_monto_py(i.get("total")),
                                st.session_state.user, str(datetime.datetime.now())
                            ])
                        s.update(label="✅ ¡Listo!", state="complete")
                    st.balloons()

    elif menu == "📊 Historial":
        st.title("📊 Todos los Gastos")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            search = st.text_input("🔍 Buscar repuesto...")
            if search:
                df = df[df.apply(lambda r: r.astype(str).str.contains(search, case=False).any(), axis=1)]
            st.dataframe(df, use_container_width=True)

    elif menu == "📅 Reporte Mensual":
        st.title("📅 Generar Reporte para Contabilidad")
        sh = conectar_sheets()
        if sh:
            df = pd.DataFrame(sh.worksheet("Gastos").get_all_records())
            if not df.empty:
                # Convertir fechas para filtrar
                df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
                meses = df['Fecha'].dt.strftime('%Y-%m').unique().tolist()
                mes_sel = st.selectbox("Selecciona el mes del reporte", meses)
                
                reporte_df = df[df['Fecha'].dt.strftime('%Y-%m') == mes_sel]
                st.write(f"### Resumen de {mes_sel}")
                st.dataframe(reporte_df)
                
                # Botón de Descarga Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    reporte_df.to_excel(writer, index=False, sheet_name='Reporte')
                
                st.download_button(
                    label="📥 Descargar Reporte Excel",
                    data=output.getvalue(),
                    file_name=f"Reporte_Taller_{mes_sel}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else: st.info("No hay datos para generar reportes.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
