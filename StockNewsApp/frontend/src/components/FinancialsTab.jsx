import { useState, useCallback } from 'react';
import {
  ComposedChart, LineChart,
  Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';

const API = 'http://localhost:8000';
const CHART_H = 280;

const C = {
  amber:  '#f59e0b',
  blue:   '#3b82f6',
  red:    '#ef4444',
  green:  '#22c55e',
  purple: '#a855f7',
  orange: '#f97316',
  price:  '#f87171',
};

const axisStyle  = { fill: '#94a3b8', fontSize: 11 };
const gridProps  = { strokeDasharray: '3 3', stroke: 'rgba(255,255,255,0.08)' };
const cardStyle  = {
  background: 'rgba(30, 41, 59, 0.7)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 12,
  padding: '1rem',
};
const legendStyle = { wrapperStyle: { fontSize: 11, color: '#94a3b8', paddingTop: 4 } };

function fmtDate(v) {
  if (!v) return '';
  return String(v).slice(0, 7);
}

function CustomTooltip({ active, payload, label, unit = '' }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#1e293b', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 8, padding: '0.5rem 0.75rem', fontSize: '0.78rem' }}>
      <p style={{ margin: '0 0 0.3rem', color: '#94a3b8' }}>{label}</p>
      {payload.map(p => (
        <p key={p.dataKey} style={{ margin: '0.1rem 0', color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}{unit}
        </p>
      ))}
    </div>
  );
}

function ChartCard({ title, children, loading, error, extra }) {
  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
        <h3 style={{ margin: 0, fontSize: '0.9rem', color: '#e2e8f0', fontWeight: 600 }}>{title}</h3>
        {extra}
      </div>
      {loading ? (
        <div style={{ height: CHART_H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b' }}>
          載入中…
        </div>
      ) : error ? (
        <div style={{ height: CHART_H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ef4444', fontSize: '0.8rem', textAlign: 'center', padding: '0 1rem' }}>
          {error}
        </div>
      ) : children}
    </div>
  );
}

function EmptyChart() {
  return (
    <div style={{ height: CHART_H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: '0.85rem' }}>
      輸入股號後點擊「顯示」
    </div>
  );
}

const initChart = () => ({ data: [], loading: false, error: null });

export default function FinancialsTab() {
  const [inputId, setInputId]     = useState('');
  const [stockId, setStockId]     = useState('');
  const [minShares, setMinShares] = useState(400);
  const [pendingShares, setPendingShares] = useState(400);

  const [charts, setCharts] = useState({
    revenue:     initChart(),
    eps:         initChart(),
    margins:     initChart(),
    revGrowth:   initChart(),
    turnover:    initChart(),
    shareholders: initChart(),
  });

  const setChart = useCallback((key, updates) =>
    setCharts(prev => ({ ...prev, [key]: { ...prev[key], ...updates } })), []);

  const fetchChart = useCallback(async (key, path, id, extra = '') => {
    setChart(key, { loading: true, error: null, data: [] });
    try {
      const res = await fetch(`${API}/api/financials/${id}/${path}${extra}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      setChart(key, { data: json.data ?? [], loading: false });
    } catch (e) {
      setChart(key, { error: e.message, loading: false, data: [] });
    }
  }, [setChart]);

  const handleSearch = useCallback(() => {
    const id = inputId.trim();
    if (!id) return;
    setStockId(id);
    fetchChart('revenue',     'revenue', id);
    fetchChart('eps',         'eps', id);
    fetchChart('margins',     'margins', id);
    fetchChart('revGrowth',   'revenue-growth', id);
    fetchChart('turnover',    'turnover-days', id);
    fetchChart('shareholders','shareholders', id, `?min_shares=${minShares}`);
  }, [inputId, minShares, fetchChart]);

  const applyShares = useCallback(() => {
    if (!stockId) return;
    setMinShares(pendingShares);
    fetchChart('shareholders', 'shareholders', stockId, `?min_shares=${pendingShares}`);
  }, [stockId, pendingShares, fetchChart]);

  const { revenue, eps, margins, revGrowth, turnover, shareholders } = charts;

  return (
    <div style={{ paddingBottom: '2rem' }}>

      {/* ── Search bar ─────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="輸入股號（例：2330）"
          value={inputId}
          onChange={e => setInputId(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          style={{
            padding: '0.6rem 1rem', borderRadius: 8, width: 200,
            border: '1px solid rgba(255,255,255,0.15)',
            background: 'rgba(255,255,255,0.05)', color: 'white', fontSize: '1rem',
          }}
        />
        <button className="btn" onClick={handleSearch} disabled={!inputId.trim()}>
          顯示
        </button>
        {stockId && (
          <span style={{ color: '#64748b', fontSize: '0.9rem' }}>
            目前：<strong style={{ color: '#e2e8f0' }}>{stockId}</strong>
          </span>
        )}
      </div>

      {/* ── Charts 2-column grid ───────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>

        {/* 1. Monthly Revenue */}
        <ChartCard title="每月營收 (億元)" loading={revenue.loading} error={revenue.error}>
          {revenue.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <ComposedChart data={revenue.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} tickFormatter={fmtDate} interval="preserveStartEnd" />
                <YAxis yAxisId="l" tick={axisStyle} />
                <YAxis yAxisId="r" orientation="right" tick={axisStyle} />
                <Tooltip content={<CustomTooltip />} />
                <Legend {...legendStyle} />
                <Bar    yAxisId="l" dataKey="value" name="月營收(億)" fill={C.amber} opacity={0.85} />
                <Line   yAxisId="r" dataKey="price" name="股價" stroke={C.price} dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

        {/* 2. Quarterly EPS */}
        <ChartCard title="單季 EPS (元)" loading={eps.loading} error={eps.error}>
          {eps.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <ComposedChart data={eps.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} />
                <YAxis yAxisId="l" tick={axisStyle} />
                <YAxis yAxisId="r" orientation="right" tick={axisStyle} />
                <Tooltip content={<CustomTooltip />} />
                <Legend {...legendStyle} />
                <Bar    yAxisId="l" dataKey="value" name="EPS(元)" fill={C.amber} opacity={0.85} />
                <Line   yAxisId="r" dataKey="price" name="股價" stroke={C.price} dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

        {/* 3. Profit Margins */}
        <ChartCard title="利潤比率 (%)" loading={margins.loading} error={margins.error}>
          {margins.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <LineChart data={margins.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} />
                <YAxis tick={axisStyle} unit="%" />
                <Tooltip content={<CustomTooltip unit="%" />} />
                <Legend {...legendStyle} />
                <Line dataKey="gross_margin"     name="毛利率"     stroke={C.amber}  dot={false} strokeWidth={2} />
                <Line dataKey="operating_margin" name="營業利益率"  stroke={C.blue}   dot={false} strokeWidth={2} />
                <Line dataKey="pre_tax_margin"   name="稅前淨利率"  stroke={C.red}    dot={false} strokeWidth={2} />
                <Line dataKey="net_margin"       name="稅後淨利率"  stroke={C.green}  dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

        {/* 4. Revenue Growth */}
        <ChartCard title="長短期月營收年增率 (%)" loading={revGrowth.loading} error={revGrowth.error}>
          {revGrowth.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <ComposedChart data={revGrowth.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} tickFormatter={fmtDate} interval="preserveStartEnd" />
                <YAxis yAxisId="l" tick={axisStyle} unit="%" />
                <YAxis yAxisId="r" orientation="right" tick={axisStyle} />
                <ReferenceLine yAxisId="l" y={0} stroke="rgba(255,255,255,0.2)" />
                <Tooltip content={<CustomTooltip />} />
                <Legend {...legendStyle} />
                <Line yAxisId="l" dataKey="rev3_yoy"  name="近3月"  stroke={C.orange} dot={false} strokeWidth={2} />
                <Line yAxisId="l" dataKey="rev6_yoy"  name="近6月"  stroke={C.green}  dot={false} strokeWidth={2} />
                <Line yAxisId="l" dataKey="rev12_yoy" name="近12月" stroke={C.purple} dot={false} strokeWidth={2} />
                <Line yAxisId="r" dataKey="price"     name="股價"   stroke={C.price}  dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

        {/* 5. Turnover Days */}
        <ChartCard title="週轉天數 (天)" loading={turnover.loading} error={turnover.error}>
          {turnover.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <LineChart data={turnover.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} />
                <YAxis tick={axisStyle} unit="天" />
                <Tooltip content={<CustomTooltip unit="天" />} />
                <Legend {...legendStyle} />
                <Line dataKey="dso"              name="應收帳款收現天數" stroke={C.amber} dot={false} strokeWidth={2} />
                <Line dataKey="dio"              name="存貨週轉天數"    stroke={C.blue}  dot={false} strokeWidth={2} />
                <Line dataKey="operating_cycle"  name="營業週轉天數"   stroke={C.red}   dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

        {/* 6. Major Shareholders */}
        <ChartCard
          title="大股東持股比率 (%)"
          loading={shareholders.loading}
          error={shareholders.error}
          extra={
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>≥</span>
              <input
                type="number"
                value={pendingShares}
                min={1}
                onChange={e => setPendingShares(Number(e.target.value))}
                onKeyDown={e => e.key === 'Enter' && applyShares()}
                style={{
                  width: 64, padding: '0.2rem 0.4rem', borderRadius: 4, fontSize: '0.8rem',
                  border: '1px solid rgba(255,255,255,0.15)',
                  background: 'rgba(255,255,255,0.05)', color: 'white',
                }}
              />
              <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>張</span>
              <button
                className="btn"
                style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
                onClick={applyShares}
                disabled={!stockId}
              >
                套用
              </button>
            </div>
          }
        >
          {shareholders.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={CHART_H}>
              <ComposedChart data={shareholders.data}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" tick={axisStyle} tickFormatter={fmtDate} interval="preserveStartEnd" />
                <YAxis yAxisId="l" tick={axisStyle} unit="%" domain={['auto', 'auto']} />
                <YAxis yAxisId="r" orientation="right" tick={axisStyle} />
                <Tooltip content={<CustomTooltip />} />
                <Legend {...legendStyle} />
                <Line yAxisId="l" dataKey="value" name="大股東持股%" stroke={C.amber} dot={false} strokeWidth={2} />
                <Line yAxisId="r" dataKey="price" name="股價"        stroke={C.price} dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </ChartCard>

      </div>
    </div>
  );
}
