import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import time

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - Carga Masiva", page_icon="🚀", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Falta la API Key en los Secrets.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y UTILIDADES
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
    nombre_hoja = f"Gasto-{nombre_usuario}"
    try:
        return sh.worksheet(nombre_hoja)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=nombre_hoja, rows="2000", cols="20")
        columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
        ws.insert_row(columnas, 1)
        return ws

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        for row in ws.get_all_records():
            if str(row['username']).lower() == str(u).lower() and str(row['password']) == str(p):
                return row.get('rol', 'usuario')
        return None
    except: return None

# ==========================================
# 🧠 3. MOTOR DE MONEDA Y IA
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
        response = requests.post(url, json=payload, timeout=30)
        texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Taller Pro")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Ingresar"):
        rol = check_login(u, p)
        if rol:
            st.session_state.auth = True
            st.session_state.user = u
            st.session_state.rol = rol
            st.rerun()
        else: st.error("Credenciales incorrectas.")
else:
    menu = st.sidebar.radio("Navegación", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    # --- MÓDULO 1: CARGA MASIVA ---
    if menu == "📥 Carga Masiva":
        st.title("📥 Digitalización por Lote (Máx. 20)")
        # ACTIVAMOS MULTIPLE_FILES
        files = st.file_uploader("Arrastra aquí tus facturas", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} archivos"):
            all_items = []
            progreso = st.progress(0)
            status = st.empty()
            
            for i, f in enumerate(files):
                porcentaje = (i + 1) / len(files)
                status.info(f"🔎 Analizando archivo {i+1} de {len(files)}: **{f.name}**")
                
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    for item in datos.get('items', []):
                        all_items.append({
                            'Fecha': datos.get('fecha', ""),
                            'Proveedor': datos.get('proveedor', ""),
                            'Factura': datos.get('nro_factura', ""),
                            'Producto': item.get('producto', ""),
                            'Cantidad': limpiar_monto_py(item.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(item.get('unitario')),
                            'Total': limpiar_monto_py(item.get('total'))
                        })
                progreso.progress(porcentaje)
                time.sleep(0.5) # Breve pausa para estabilidad
            
            st.session_state.batch_df = pd.DataFrame(all_items)
            status.success(f"✅ ¡Se han analizado {len(files)} archivos con éxito!")

        if 'batch_df' in st.session_state and not st.session_state.batch_df.empty:
            st.markdown("---")
            st.subheader("📝 Revisión de Datos Consolidados")
            st.warning("Revisa y corrige cualquier dato en la tabla antes de guardar todo en la nube.")
            
            # Editor de tabla con todos los datos de todos los archivos
            edit_df = st.data_editor(st.session_state.batch_df, use_container_width=True, num_rows="dynamic")
            
            if st.button("Guardar todo en Google Sheets", type="primary"):
                sh = conectar_sheets()
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                existentes = pd.DataFrame(ws.get_all_records())
                
                with st.spinner("Guardando en tu pestaña personal..."):
                    for _, row in edit_df.iterrows():
                        id_u = f"{row['Proveedor']}_{row['Fecha']}_{row['Factura']}_{row['Producto']}".upper().replace(" ", "")
                        
                        if not existentes.empty and 'ID_Unico' in existentes.columns:
                            if id_u in existentes['ID_Unico'].values:
                                continue # Omite duplicados silenciosamente
                        
                        ws.append_row([
                            str(row['Fecha']), str(row['Proveedor']), str(row['Factura']), 
                            row['Producto'], row['Cantidad'], "u", 
                            row['Unitario'], row['Total'], st.session_state.user, 
                            id_u, str(datetime.datetime.now())
                        ])
                
                st.success(f"✅ ¡{len(edit_df)} registros guardados!")
                st.session_state.batch_df = None
                st.balloons()

    # --- MÓDULO 2: DASHBOARD (SE MANTIENE) ---
    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Gastos")
        sh = conectar_sheets()
        todas = []
        if st.session_state.rol == "admin":
            for hoja in sh.worksheets():
                if hoja.title.startswith("Gasto-"):
                    data = hoja.get_all_records()
                    if data: todas.append(pd.DataFrame(data))
            df = pd.concat(todas) if todas else pd.DataFrame()
        else:
            ws = obtener_o_crear_pestana(sh, st.session_state.user)
            data = ws.get_all_records()
            df = pd.DataFrame(data) if data else pd.DataFrame()

        if not df.empty:
            df['Total'] = pd.to_numeric(df['Total'], errors='coerce')
            st.metric("Inversión Total", f"{df['Total'].sum():,.0f} Gs.")
            st.plotly_chart(px.pie(df, values='Total', names='Proveedor', hole=.3))
        else: st.info("Sin datos.")

    # --- MÓDULO 3: HISTORIAL (CON FILTROS) ---
    elif menu == "📅 Historial":
        st.title("📅 Mi Historial")
        sh = conectar_sheets()
        if st.session_state.rol == "admin":
            lista = [h.title for h in sh.worksheets() if h.title.startswith("Gasto-")]
            sel = st.selectbox("Ver datos de:", lista)
            df = pd.DataFrame(sh.worksheet(sel).get_all_records())
        else:
            ws = obtener_o_crear_pestana(sh, st.session_state.user)
            df = pd.DataFrame(ws.get_all_records())
            
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            # Filtro simple por mes
            meses = df['Fecha'].dt.strftime('%Y-%m').unique()
            mes_sel = st.selectbox("Filtrar por Mes", ["Todos"] + list(meses))
            if mes_sel != "Todos":
                df = df[df['Fecha'].dt.strftime('%Y-%m') == mes_sel]
            st.dataframe(df.sort_values('Fecha', ascending=False), use_container_width=True)
        else: st.info("Vacío.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
