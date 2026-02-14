import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - Gestión Multi-User", page_icon="🔐", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y GESTIÓN DE PESTAÑAS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except: return None

def obtener_o_crear_pestana(sh, nombre_usuario):
    """Asegura que cada usuario tenga su pestaña propia: Gasto-usuario"""
    nombre_hoja = f"Gasto-{nombre_usuario}"
    try:
        return sh.worksheet(nombre_hoja)
    except gspread.exceptions.WorksheetNotFound:
        # Si no existe, la creamos con los encabezados
        ws = sh.add_worksheet(title=nombre_hoja, rows="1000", cols="20")
        columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
        ws.insert_row(columnas, 1)
        return ws

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        for row in ws.get_all_records():
            if str(row['username']) == str(u) and str(row['password']) == str(p):
                return row.get('rol', 'usuario') # Retorna 'admin' o 'usuario'
        return None
    except: return None

# ==========================================
# 🧠 3. MOTOR DE MONEDA (PARAGUAY PRO)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    if not valor: return 0
    s = str(valor).replace('Gs', '').replace('$', '').replace(' ', '').strip()
    try:
        if es_cantidad:
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            if s.endswith(',00') or s.endswith('.00'): s = s[:-3]
            elif s.endswith(',0') or s.endswith('.0'): s = s[:-2]
            s = s.replace('.', '').replace(',', '')
            return int(float(s))
    except: return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, y items (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload)
        texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Sistema de Gastos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar"):
        rol = check_login(u, p)
        if rol:
            st.session_state.auth = True
            st.session_state.user = u
            st.session_state.rol = rol
            st.rerun()
        else: st.error("Usuario o clave incorrectos.")
else:
    with st.sidebar:
        st.header(f"👤 {st.session_state.user.upper()}")
        st.caption(f"Rol: {st.session_state.rol}")
        menu = st.sidebar.radio("Navegación", ["📥 Cargar Factura", "📊 Dashboard", "📅 Mi Historial", "🚀 Salir"])

    # --- MÓDULO 1: CARGA ---
    if menu == "📥 Cargar Factura":
        st.title(f"📥 Nueva Carga para: Gasto-{st.session_state.user}")
        f = st.file_uploader("Subir factura", type=["pdf", "png", "jpg", "jpeg"])
        
        if f and st.button("Procesar Documento"):
            with st.spinner("🤖 Analizando..."):
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    df = pd.DataFrame(datos['items'])
                    df['cantidad'] = df['cantidad'].apply(lambda x: limpiar_monto_py(x, True))
                    df['unitario'] = df['unitario'].apply(limpiar_monto_py)
                    df['total'] = df['total'].apply(limpiar_monto_py)
                    st.session_state.temp = {'f': datos.get('fecha'), 'p': datos.get('proveedor'), 'n': datos.get('nro_factura'), 'df': df}

        if 'temp' in st.session_state and st.session_state.temp:
            t = st.session_state.temp
            f_ed = st.text_input("Fecha", t['f'])
            p_ed = st.text_input("Proveedor", t['p'])
            n_ed = st.text_input("Nro. Factura", t['n'])
            edit_df = st.data_editor(t['df'], use_container_width=True)
            
            if st.button("Confirmar y Guardar", type="primary"):
                sh = conectar_sheets()
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                
                # Cargar datos actuales para evitar duplicados en SU pestaña
                existentes = pd.DataFrame(ws.get_all_records())
                
                for _, row in edit_df.iterrows():
                    id_u = f"{p_ed}_{f_ed}_{n_ed}_{row['producto']}".upper().replace(" ", "")
                    if not existentes.empty and id_u in existentes['ID_Unico'].values:
                        st.warning(f"⚠️ El producto '{row['producto']}' ya fue cargado por ti en esta factura.")
                        continue
                    
                    ws.append_row([f_ed, p_ed, n_ed, row['producto'], row['cantidad'], "u", row['unitario'], row['total'], st.session_state.user, id_u, str(datetime.datetime.now())])
                
                st.success("✅ Guardado en tu pestaña personal.")
                st.session_state.temp = None
                st.balloons()

    # --- MÓDULO 2: DASHBOARD (INTELIGENTE) ---
    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Gastos")
        sh = conectar_sheets()
        
        # El ADMIN puede elegir qué ver
        if st.session_state.rol == "admin":
            st.info("Eres Administrador: Puedes ver el consolidado total.")
            # Unificar todas las pestañas que empiecen con 'Gasto-'
            todas = []
            for hoja in sh.worksheets():
                if hoja.title.startswith("Gasto-"):
                    todas.append(pd.DataFrame(hoja.get_all_records()))
            df = pd.concat(todas) if todas else pd.DataFrame()
        else:
            ws = obtener_o_crear_pestana(sh, st.session_state.user)
            df = pd.DataFrame(ws.get_all_records())

        if not df.empty:
            df['total'] = pd.to_numeric(df['total'], errors='coerce')
            st.plotly_chart(px.pie(df, values='total', names='Proveedor', title="Gastos por Proveedor"))
        else: st.info("Sin datos para mostrar.")

    # --- MÓDULO 3: HISTORIAL (CON PRIVACIDAD) ---
    elif menu == "📅 Mi Historial":
        st.title(f"📅 Registros en Gasto-{st.session_state.user}")
        sh = conectar_sheets()
        
        if st.session_state.rol == "admin":
            opcion_hoja = st.selectbox("Seleccionar Hoja a Visualizar", [h.title for h in sh.worksheets() if h.title.startswith("Gasto-")])
            df = pd.DataFrame(sh.worksheet(opcion_hoja).get_all_records())
        else:
            ws = obtener_o_crear_pestana(sh, st.session_state.user)
            df = pd.DataFrame(ws.get_all_records())
            
        st.dataframe(df, use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
