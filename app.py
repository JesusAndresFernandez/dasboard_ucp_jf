import os
from dotenv import load_dotenv
import pandas as pd
import plotly.graph_objects as go
import psycopg2
from dash import Dash, Input, Output, dcc, html

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "No se encontro DATABASE_URL."
    )


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def fetch_services():
    query = """
        SELECT DISTINCT svc
        FROM public.logs
        WHERE svc IS NOT NULL
        ORDER BY svc;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    return df["svc"].tolist()


def fetch_window_logs(hours: int, svc: str):
    query = """
        WITH ref AS (
            SELECT MAX(ts) AS ref_ts
            FROM public.logs
            WHERE (%s = 'ALL' OR svc = %s)
        )
        SELECT
            l.id,
            l.ts,
            l.ingested_at,
            l.svc,
            l.url,
            l.http_method,
            l.status_code,
            l.duration
        FROM public.logs l
        CROSS JOIN ref r
        WHERE r.ref_ts IS NOT NULL
          AND l.ts >= r.ref_ts - (%s * INTERVAL '1 hour')
          AND l.ts <= r.ref_ts
          AND (%s = 'ALL' OR l.svc = %s)
        ORDER BY l.ts ASC;
    """
    params = (svc, svc, int(hours), svc, svc)
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


app = Dash(__name__)
app.title = "Analitica de Logs - PostgreSQL & Dash"

services_list = fetch_services()
service_options = [{"label": "Todos los servicios", "value": "ALL"}] + [
    {"label": s, "value": s} for s in services_list
]

card_style = {
    "border": "1px solid #dcdcdc",
    "borderRadius": "8px",
    "padding": "14px 18px",
    "backgroundColor": "#fafafa",
    "minWidth": "170px",
    "flex": "1",
}

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "maxWidth": "1200px", "margin": "0 auto", "padding": "20px"},
    children=[
        html.H2("Observabilidad y Analitica de Logs (public.logs)"),
        html.Div(
            id="window-caption",
            style={"color": "#555", "marginBottom": "16px", "fontSize": "14px"},
        ),
        html.Div(
            style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "marginBottom": "20px"},
            children=[
                html.Div(
                    style={"minWidth": "220px"},
                    children=[
                        html.Label("Servicio:", style={"fontWeight": "bold"}),
                        dcc.Dropdown(
                            id="svc-selector",
                            options=service_options,
                            value="ALL",
                            clearable=False,
                        ),
                    ],
                ),
                html.Div(
                    style={"minWidth": "200px"},
                    children=[
                        html.Label("Ventana de tiempo:", style={"fontWeight": "bold"}),
                        dcc.RadioItems(
                            id="window-selector",
                            options=[
                                {"label": " 1h", "value": 1},
                                {"label": " 3h", "value": 3},
                                {"label": " 24h", "value": 24},
                            ],
                            value=24,
                            inline=True,
                            style={"marginTop": "8px"},
                        ),
                    ],
                ),
                html.Div(
                    style={"minWidth": "240px"},
                    children=[
                        html.Label("Actualizacion automatica:", style={"fontWeight": "bold"}),
                        dcc.RadioItems(
                            id="refresh-selector",
                            options=[
                                {"label": " 10s", "value": 10_000},
                                {"label": " 60s", "value": 60_000},
                                {"label": " Pausar", "value": 0},
                            ],
                            value=10_000,
                            inline=True,
                            style={"marginTop": "8px"},
                        ),
                    ],
                ),
            ],
        ),
        dcc.Interval(id="auto-refresh", interval=10_000, n_intervals=0),
        html.Div(
            id="kpi-cards",
            style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "24px"},
        ),
        dcc.Graph(id="latency-chart"),
        dcc.Graph(id="errors-rpm-chart"),
        dcc.Graph(id="duration-boxplot"),
    ],
)


@app.callback(
    Output("auto-refresh", "interval"),
    Output("auto-refresh", "disabled"),
    Input("refresh-selector", "value"),
)
def update_interval(interval_ms):
    if not interval_ms or interval_ms <= 0:
        return 60_000, True
    return int(interval_ms), False


@app.callback(
    Output("window-caption", "children"),
    Output("kpi-cards", "children"),
    Output("latency-chart", "figure"),
    Output("errors-rpm-chart", "figure"),
    Output("duration-boxplot", "figure"),
    Input("svc-selector", "value"),
    Input("window-selector", "value"),
    Input("auto-refresh", "n_intervals"),
)
def refresh_dashboard(svc, hours, _n):
    df = fetch_window_logs(hours=hours, svc=svc)

    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_white", title="Sin datos para la seleccion actual")

    if df.empty:
        cards = [
            html.Div(style=card_style, children=[html.Div("Response time"), html.H3("-")]),
            html.Div(style=card_style, children=[html.Div("Throughout (RPM)"), html.H3("-")]),
            html.Div(style=card_style, children=[html.Div("Error count (4xx y 5xx)"), html.H3("0 (4xx: 0 | 5xx: 0)")]),
            html.Div(style=card_style, children=[html.Div("P95 / P99 response time"), html.H3("- / -")]),
        ]
        return (
            f"Ventana: ultimas {hours}h | Servicio: {svc} | Sin registros en el rango.",
            cards,
            empty_fig,
            empty_fig,
            empty_fig,
        )

    ref_max = df["ts"].max()
    ref_min = df["ts"].min()

    avg_resp = df["duration"].mean()
    p95_resp = df["duration"].quantile(0.95)
    p99_resp = df["duration"].quantile(0.99)

    err_4xx = int(df["status_code"].between(400, 499).sum())
    err_5xx = int(df["status_code"].between(500, 599).sum())
    err_total = err_4xx + err_5xx

    span_minutes = max((ref_max - ref_min).total_seconds() / 60.0, 1.0)
    rpm_avg = len(df) / span_minutes

    cards = [
        html.Div(
            style=card_style,
            children=[
                html.Div("Response time (promedio)", style={"fontSize": "13px", "color": "#555"}),
                html.H3(f"{avg_resp:.1f} ms", style={"margin": "6px 0 0 0"}),
            ],
        ),
        html.Div(
            style=card_style,
            children=[
                html.Div("Throughout (RPM)", style={"fontSize": "13px", "color": "#555"}),
                html.H3(f"{rpm_avg:.2f}", style={"margin": "6px 0 0 0"}),
                html.Div(f"Total logs: {len(df):,}", style={"fontSize": "12px", "color": "#777"}),
            ],
        ),
        html.Div(
            style=card_style,
            children=[
                html.Div("Error count (4xx y 5xx)", style={"fontSize": "13px", "color": "#555"}),
                html.H3(f"{err_total:,}", style={"margin": "6px 0 0 0"}),
                html.Div(f"4xx: {err_4xx:,} | 5xx: {err_5xx:,}", style={"fontSize": "12px", "color": "#777"}),
            ],
        ),
        html.Div(
            style=card_style,
            children=[
                html.Div("P95 / P99 response time", style={"fontSize": "13px", "color": "#555"}),
                html.H3(f"{p95_resp:.0f} / {p99_resp:.0f} ms", style={"margin": "6px 0 0 0"}),
            ],
        ),
    ]

    df_min = (
        df.set_index("ts")
        .resample("1min")
        .agg(
            rpm=("id", "count"),
            avg_duration=("duration", "mean"),
            p95_duration=("duration", lambda s: s.quantile(0.95) if len(s) else None),
            p99_duration=("duration", lambda s: s.quantile(0.99) if len(s) else None),
            err_4xx=("status_code", lambda s: s.between(400, 499).sum()),
            err_5xx=("status_code", lambda s: s.between(500, 599).sum()),
        )
        .dropna(how="all")
    )

    fig_lat = go.Figure()
    fig_lat.add_trace(
        go.Scatter(x=df_min.index, y=df_min["avg_duration"], mode="lines", name="Promedio (ms)")
    )
    fig_lat.add_trace(
        go.Scatter(x=df_min.index, y=df_min["p95_duration"], mode="lines", name="P95 (ms)")
    )
    fig_lat.add_trace(
        go.Scatter(x=df_min.index, y=df_min["p99_duration"], mode="lines", name="P99 (ms)")
    )
    fig_lat.update_layout(
        title="Response time: Promedio, P95 y P99 por minuto",
        xaxis_title="Tiempo (UTC)",
        yaxis_title="Duracion (ms)",
        template="plotly_white",
        hovermode="x unified",
    )

    fig_err_rpm = go.Figure()
    fig_err_rpm.add_trace(
        go.Bar(x=df_min.index, y=df_min["err_4xx"], name="Errores 4xx")
    )
    fig_err_rpm.add_trace(
        go.Bar(x=df_min.index, y=df_min["err_5xx"], name="Errores 5xx")
    )
    fig_err_rpm.add_trace(
        go.Scatter(x=df_min.index, y=df_min["rpm"], mode="lines", name="Throughout (RPM)")
    )
    fig_err_rpm.update_layout(
        barmode="stack",
        title="Error count (4xx y 5xx) y Throughout (RPM) por minuto",
        xaxis_title="Tiempo (UTC)",
        yaxis_title="Cantidad / RPM",
        template="plotly_white",
        hovermode="x unified",
    )

    group_col = "svc" if svc == "ALL" else "http_method"
    group_label = "Servicio" if svc == "ALL" else "Metodo HTTP"
    fig_box = go.Figure()
    for category, grp in df.groupby(group_col):
        fig_box.add_trace(
            go.Box(
                y=grp["duration"],
                name=str(category),
                boxpoints="outliers",
            )
        )
    fig_box.update_layout(
        title=f"Distribucion de duracion (Box Plot) por {group_label}",
        xaxis_title=group_label,
        yaxis_title="Duracion (ms)",
        template="plotly_white",
    )

    caption = (
        f"Anclado al ultimo log disponible: {ref_max.strftime('%Y-%m-%d %H:%M:%S UTC')} "
        f"| Rango consultado: {ref_min.strftime('%H:%M:%S')} a {ref_max.strftime('%H:%M:%S UTC')} "
        f"| Servicio: {svc}"
    )

    return caption, cards, fig_lat, fig_err_rpm, fig_box


if __name__ == "__main__":
    app.run(debug=True)