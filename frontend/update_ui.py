
import os

file_path = r"c:\Users\kunha\Documents\Python\taiwan-stock-dashboard\frontend\index.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Define the NEW CorrelationChart code
new_chart_code = """        // --- Correlation Analysis Components ---
        const CorrelationChart = ({ data, series1Name, series2Name, series1Key = 'stock_price', series2Key = 'metal_price', title }) => {
            const chartRef = useRef(null);

            useEffect(() => {
                if (!chartRef.current || !data || data.length === 0) return;

                const series1Data = data.map(d => d[series1Key]);
                const series2Data = data.map(d => d[series2Key]);

                // Calculate constraints for dual y-axis
                const min1 = Math.min(...series1Data) * 0.95;
                const max1 = Math.max(...series1Data) * 1.05;
                const min2 = Math.min(...series2Data) * 0.95;
                const max2 = Math.max(...series2Data) * 1.05;

                const options = {
                    series: [
                        {
                            name: series1Name,
                            type: 'line',
                            data: data.map(d => ({ x: d.date, y: d[series1Key] }))
                        },
                        {
                            name: series2Name,
                            type: 'line',
                            data: data.map(d => ({ x: d.date, y: d[series2Key] }))
                        }
                    ],
                    chart: {
                        id: `chart-${Math.random().toString(36).substr(2, 9)}`,
                        type: 'line',
                        height: 400,
                        background: 'transparent',
                        toolbar: {
                            show: true,
                            tools: { download: false }
                        }
                    },
                    colors: ['#0ea5e9', '#f59e0b'], 
                    stroke: { width: [3, 3], curve: 'smooth' },
                    title: {
                        text: title,
                        align: 'left',
                        style: { color: '#f8fafc', fontSize: '18px' }
                    },
                    xaxis: {
                        type: 'category',
                        tickAmount: 10,
                        labels: {
                            style: { colors: '#94a3b8' },
                            formatter: (val) => (typeof val === 'string' && val.length > 5) ? val.slice(5) : val
                        }
                    },
                    yaxis: [
                        {
                            seriesName: series1Name,
                            min: min1,
                            max: max1,
                            title: { text: series1Name, style: { color: '#0ea5e9' } },
                            labels: { style: { colors: '#0ea5e9' }, formatter: (val) => val.toFixed(1) }
                        },
                        {
                            seriesName: series2Name,
                            opposite: true,
                            min: min2,
                            max: max2,
                            title: { text: series2Name, style: { color: '#f59e0b' } },
                            labels: { style: { colors: '#f59e0b' }, formatter: (val) => val.toFixed(2) }
                        }
                    ],
                    grid: { borderColor: '#334155', strokeDashArray: 3 },
                    theme: { mode: 'dark' },
                    legend: { position: 'top', horizontalAlign: 'right' }
                };

                const chart = new ApexCharts(chartRef.current, options);
                chart.render();

                return () => chart.destroy();
            }, [data, series1Name, series2Name, series1Key, series2Key, title]);

            const handleDownload = async () => {
                const element = chartRef.current.parentElement; 
                if (!element) return;
                try {
                    const canvas = await window.html2canvas(element, { backgroundColor: '#0f172a', scale: 2 });
                    canvas.toBlob((blob) => {
                        window.saveAs(blob, `${title.replace(/\s+/g, '_')}.jpg`);
                    }, 'image/jpeg');
                } catch (err) { console.error(err); }
            };

            return (
                <div className="relative group">
                    <button onClick={handleDownload} className="absolute top-2 right-12 z-10 bg-slate-800/80 hover:bg-slate-700 p-2 rounded text-slate-300 hover:text-white transition-colors opacity-0 group-hover:opacity-100">
                        <i data-lucide="download" className="w-4 h-4"></i>
                    </button>
                    <div ref={chartRef} className="w-full"></div>
                </div>
            );
        };"""

# Define the NEW CorrelationAnalysisSection code
new_section_code = """        const CorrelationAnalysisSection = () => {
            const [stockInputs, setStockInputs] = useState(['2002.TW', '2014.TW']);
            const [metal, setMetal] = useState('Nickel');
            const [startDate, setStartDate] = useState(new Date(new Date().setFullYear(new Date().getFullYear() - 1)).toISOString().split('T')[0]);
            const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
            const [results, setResults] = useState(null);
            const [loading, setLoading] = useState(false);

            const metals = ['None', 'Aluminium', 'Copper', 'Nickel', 'Lead', 'Zinc', 'Tin', 'Platinum', 'Gold', 'Silver'];

            const handleAddStock = () => setStockInputs([...stockInputs, '']);
            const handleRemoveStock = (index) => setStockInputs(stockInputs.filter((_, i) => i !== index));
            const handleStockChange = (index, value) => {
                const newInputs = [...stockInputs];
                newInputs[index] = value;
                setStockInputs(newInputs);
            };

            const handleAnalyze = async (overrideMetal = null) => {
                setLoading(true);
                setResults(null);

                const stockIds = stockInputs.map(s => s.trim()).filter(s => s);
                if (stockIds.length === 0) {
                    alert('Please enter at least one stock ID');
                    setLoading(false);
                    return;
                }

                let metalToSend = (overrideMetal !== null) ? overrideMetal : metal;
                if (metalToSend === 'None') metalToSend = null;

                try {
                    const response = await axios.post('/api/analyze', {
                        stock_ids: stockIds,
                        metal: metalToSend,
                        start_date: startDate,
                        end_date: endDate
                    });
                    setResults(response.data);
                } catch (error) {
                    console.error("Analysis Error:", error);
                    alert("Analysis failed.");
                } finally {
                    setLoading(false);
                }
            };

            return (
                <div className="space-y-8">
                    {/* Controls */}
                    <div className="glass-panel p-6 rounded-2xl">
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                            
                            {/* Stock IDs */}
                            <div className="space-y-2 lg:col-span-2">
                                <label className="text-sm text-slate-400 font-semibold flex justify-between items-center">
                                    <span>Stock IDs</span>
                                    <div className="flex gap-2">
                                         <button onClick={() => handleAnalyze('None')} className="text-blue-400 text-xs hover:text-blue-300 transition-colors flex items-center gap-1 font-bold border border-blue-500/30 px-2 py-1 rounded">
                                            <i data-lucide="git-compare" className="w-3 h-3"></i> Compare Stocks
                                        </button>
                                        <button onClick={handleAddStock} className="text-emerald-400 text-xs hover:text-emerald-300 transition-colors flex items-center gap-1">
                                            <i data-lucide="plus-circle" className="w-3 h-3"></i> Add Stock
                                        </button>
                                    </div>
                                </label>
                                <div className="space-y-2 max-h-48 overflow-y-auto pr-2 custom-scrollbar">
                                    {stockInputs.map((input, idx) => (
                                        <div key={idx} className="flex gap-2 items-center animate-fade-in">
                                            <input 
                                                type="text" 
                                                value={input} 
                                                onChange={(e) => handleStockChange(idx, e.target.value)}
                                                className="flex-1 bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-emerald-500 focus:outline-none placeholder-slate-600"
                                                placeholder="e.g. 2002.TW"
                                            />
                                            {stockInputs.length > 1 && (
                                                <button onClick={() => handleRemoveStock(idx)} className="p-2 text-red-500 hover:bg-slate-800/50 rounded-lg transition-colors">
                                                    <i data-lucide="trash-2" className="w-4 h-4"></i>
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm text-slate-400 font-semibold">Metal</label>
                                <select 
                                    value={metal} 
                                    onChange={(e) => setMetal(e.target.value)}
                                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:ring-2 focus:ring-emerald-500 focus:outline-none cursor-pointer"
                                >
                                    {metals.map(m => <option key={m} value={m}>{m}</option>)}
                                </select>
                            </div>
                            
                            <div className="space-y-2">
                                <label className="text-sm text-slate-400 font-semibold">Date Range</label>
                                <div className="flex gap-2">
                                    <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-1/2 bg-slate-800/50 border border-slate-700 rounded-lg px-2 py-2.5 text-white text-xs" />
                                    <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-1/2 bg-slate-800/50 border border-slate-700 rounded-lg px-2 py-2.5 text-white text-xs" />
                                </div>
                            </div>

                             <div className="flex items-end">
                                <button 
                                    onClick={() => handleAnalyze()} 
                                    disabled={loading}
                                    className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 px-8 rounded-lg shadow-lg shadow-emerald-900/20 hover:shadow-emerald-900/40 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                                >
                                    {loading ? <i data-lucide="loader" className="animate-spin"></i> : <i data-lucide="play-circle"></i>}
                                    {loading ? 'Running...' : 'Run Analysis'}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Results Container */}
                    <div className="space-y-12">
                        
                        {/* Stock vs Metal Results */}
                        {results && results.stock_results && results.metal_ticker !== 'None' && (
                            <div className="space-y-4">
                                <h3 className="text-xl font-bold text-white border-b border-slate-700 pb-2">Stock vs Metal ({metal})</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-fade-in">
                                    {results.stock_results.map((data) => {
                                        const stockId = data.stock_id;
                                        if (data.error) return null;
                                        const correlation = data.correlation || 0;
                                        const corrColor = correlation > 0.7 ? 'text-emerald-400' : correlation < -0.7 ? 'text-red-400' : 'text-slate-400';
                                        return (
                                            <div key={stockId} className="glass-panel p-6 rounded-2xl">
                                                <div className="flex justify-between items-start mb-4 border-b border-slate-700 pb-4">
                                                    <div>
                                                        <h3 className="text-xl font-bold text-white">{stockId} <span className="text-slate-500 text-sm">vs</span> {metal}</h3>
                                                        <div className="mt-1"><span className="text-slate-400 text-sm">Correlation: </span><span className={`text-2xl font-bold ${corrColor}`}>{correlation.toFixed(4)}</span></div>
                                                    </div>
                                                </div>
                                                <CorrelationChart 
                                                    data={data.data} 
                                                    series1Name={`${stockId} Price`} series2Name={`${metal} Price`}
                                                    series1Key="stock_price" series2Key="metal_price"
                                                    title={`${stockId} vs ${metal}`}
                                                />
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Stock vs Stock Results */}
                        {results && results.stock_vs_stock && results.stock_vs_stock.length > 0 && (
                            <div className="space-y-4">
                                <h3 className="text-xl font-bold text-white border-b border-slate-700 pb-2">Stock Comparison</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-fade-in">
                                    {results.stock_vs_stock.map((data, idx) => {
                                        const correlation = data.correlation;
                                        const corrColor = correlation > 0.7 ? 'text-emerald-400' : correlation < -0.7 ? 'text-red-400' : 'text-slate-400';
                                        return (
                                            <div key={idx} className="glass-panel p-6 rounded-2xl">
                                                <div className="flex justify-between items-start mb-4 border-b border-slate-700 pb-4">
                                                    <div>
                                                        <h3 className="text-xl font-bold text-white">{data.stock1} <span className="text-slate-500 text-sm">vs</span> {data.stock2}</h3>
                                                        <div className="mt-1"><span className="text-slate-400 text-sm">Correlation: </span><span className={`text-2xl font-bold ${corrColor}`}>{correlation.toFixed(4)}</span></div>
                                                    </div>
                                                </div>
                                                <CorrelationChart 
                                                    data={data.data} 
                                                    series1Name={`${data.stock1} Price`} series2Name={`${data.stock2} Price`}
                                                    series1Key="price1" series2Key="price2"
                                                    title={`${data.stock1} vs ${data.stock2}`}
                                                />
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            );
        };"""

# Split file at header
parts = content.split("// --- Correlation Analysis Components ---")
if len(parts) > 1:
    pre_content = parts[0]
    remainder = parts[1]
    
    # Updated anchor: // --- App ---
    app_start_idx = remainder.find("// --- App ---")
    if app_start_idx != -1:
        post_content = remainder[app_start_idx:]
        
        # Construct the new content
        final_content = pre_content + "\\n" + new_chart_code + "\\n\\n" + new_section_code + "\\n\\n" + post_content
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        print("Success: File updated.")
    else:
        print("Error: Could not find '// --- App ---' anchor.")
else:
    print("Error: Could not find Correlation Components header.")

