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
st.set_page_config(page_title="Taller Pro - Gestión Inteligente", page_icon="🔧", layout="wide")

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
        ws = sh.add_worksheet(title=nombre_hoja, rows="1000", cols="20")
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
# 🧠 3. MOTOR DE MONEDA (PARAGUAY FIXED)
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
            # Eliminamos .00 o ,00 que confunden al Guaraní
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
        st.title(f"📥 Nueva Carga")
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
            # Renombramos columnas para que coincidan con Sheets
            t['df'].columns = ["Producto", "Cantidad", "Unitario", "Total"]
            edit_df = st.data_editor(t['df'], use_container_width=True)
            
            if st.button("Confirmar y Guardar", type="primary"):
                sh = conectar_sheets()
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                existentes = pd.DataFrame(ws.get_all_records())
                
                for _, row in edit_df.iterrows():
                    id_u = f"{p_ed}_{f_ed}_{n_ed}_{row['Producto']}".upper().replace(" ", "")
                    if not existentes.empty and 'ID_Unico' in existentes.columns:
                        if id_u in existentes['ID_Unico'].values:
                            st.warning(f"⚠️ El producto '{row['Producto']}' ya existe.")
                            continue
                    
                    ws.append_row([f_ed, p_ed, n_ed, row['Producto'], row['Cantidad'], "u", row['Unitario'], row['Total'], st.session_state.user, id_u, str(datetime.datetime.now())])
                
                st.success("✅ Guardado en tu pestaña personal.")
                st.session_state.temp = None
                st.balloons()

    # --- MÓDULO 2: DASHBOARD (CORREGIDO) ---
    elif menu == "📊 Dashboard":
        st.title("📊 Análisis de Gastos")
        sh = conectar_sheets()
        
        todas = []
        if st.session_state.rol == "admin":
            st.info("Vista de Administrador: Consolidado de todas las pestañas.")
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
            # FIX: Aseguramos que los nombres coincidan con las mayúsculas de Sheets
            df['Total'] = pd.to_numeric(df['Total'], errors='coerce')
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            
            c1, c2 = st.columns(2)
            # Métrica de Gasto Total
            total_gs = df['Total'].sum()
            c1.metric("Gasto Total Acumulado", f"{total_gs:,.0f} Gs.")
            
            # Gráfico de Pie por Proveedor
            fig = px.pie(df, values='Total', names='Proveedor', title="Inversión por Proveedor")
            st.plotly_chart(fig, use_container_width=True)
        else: st.info("No hay datos cargados para generar el dashboard.")

    # --- MÓDULO 3: HISTORIAL (CON FILTROS DE FECHA) ---
    elif menu == "📅 Mi Historial":
        st.title(f"📅 Historial de Gastos")
        sh = conectar_sheets()
        
        if st.session_state.rol == "admin":
            lista_hojas = [h.title for h in sh.worksheets() if h.title.startswith("Gasto-")]
            hoja_sel = st.selectbox("Auditar Hoja de:", lista_hojas)
            df = pd.DataFrame(sh.worksheet(hoja_sel).get_all_records())
        else:
            ws = obtener_o_crear_pestana(sh, st.session_state.user)
            df = pd.DataFrame(ws.get_all_records())
            
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            
            # --- SECCIÓN DE FILTROS ---
            st.markdown("### 🔍 Filtrar por Fecha")
            col_f1, col_f2, col_f3 = st.columns(3)
            
            with col_f1:
                filtro_tipo = st.selectbox("Rango Predefinido", ["Todo", "Esta Semana", "Este Mes", "Personalizado"])
            
            hoy = datetime.date.today()
            if filtro_tipo == "Esta Semana":
                inicio = hoy - datetime.timedelta(days=hoy.weekday())
                fin = inicio + datetime.timedelta(days=6)
            elif filtro_tipo == "Este Mes":
                inicio = hoy.replace(day=1)
                # Cálculo fin de mes
                siguiente_mes = hoy.replace(day=28) + datetime.timedelta(days=4)
                fin = siguiente_mes - datetime.timedelta(days=siguiente_mes.day)
            elif filtro_tipo == "Personalizado":
                with col_f2:
                    inicio = st.date_input("Desde", hoy - datetime.timedelta(days=30))
                with col_f3:
                    fin = st.date_input("Hasta", hoy)
            else:
                inicio, fin = None, None

            # Aplicar filtro si existe
            if inicio and fin:
                mask = (df['Fecha'].dt.date >= inicio) & (df['Fecha'].dt.date <= fin)
                df_filtrado = df.loc[mask]
                st.write(f"Mostrando datos desde **{inicio}** hasta **{fin}**")
            else:
                df_filtrado = df

            st.dataframe(df_filtrado.sort_values(by='Fecha', ascending=False), use_container_width=True)
            
            # Resumen del filtro
            st.info(f"Subtotal en este rango: **{df_filtrado['Total'].sum():,.0f} Gs.**")
        else:
            st.info("Aún no tienes registros cargados.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
