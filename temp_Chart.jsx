import { useRef } from 'react';
import html2canvas from 'html2canvas';
import { saveAs } from 'file-saver';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { Download } from 'lucide-react';

const Chart = ({ data, title, line1Key, line2Key, line1Name, line2Name, line1Color = "#8884d8", line2Color = "#82ca9d" }) => {
    const chartRef = useRef(null);

    const handleDownload = async () => {
        if (chartRef.current) {
            const canvas = await html2canvas(chartRef.current, {
                backgroundColor: '#1f2937' // Match bg-gray-800
            });
            canvas.toBlob((blob) => {
                saveAs(blob, `${title.replace(/\s+/g, '_')}_chart.jpg`);
            });
        }
    };

    if (!data || data.length === 0) return (
        <div className="w-full h-[300px] bg-gray-800 p-4 rounded-lg shadow-lg flex items-center justify-center text-gray-400 border border-gray-700">
            No data available for {title}
        </div>
    );

    return (
        <div ref={chartRef} className="w-full h-[450px] bg-gray-800 p-4 rounded-lg shadow-lg border border-gray-700 relative">
            <div className="flex justify-between items-center mb-2 pl-2 border-l-4 border-emerald-500">
                <h3 className="text-lg font-semibold text-gray-200">{title}</h3>
                <button
                    onClick={handleDownload}
                    className="flex items-center gap-1 bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-1 rounded text-sm transition-colors border border-gray-600"
                    title="Save as JPG"
                >
                    <Download size={16} />
                    Save
                </button>
            </div>
            <ResponsiveContainer width="100%" height="90%">
                <LineChart data={data} margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                    <XAxis dataKey="date" stroke="#888" tick={{ fontSize: 12 }} />
                    <YAxis yAxisId="left" domain={['auto', 'auto']} stroke={line1Color} label={{ value: line1Name, angle: -90, position: 'insideLeft', fill: line1Color, fontSize: 12 }} />
                    <YAxis yAxisId="right" domain={['auto', 'auto']} orientation="right" stroke={line2Color} label={{ value: line2Name, angle: 90, position: 'insideRight', fill: line2Color, fontSize: 12 }} />
                    <Tooltip
                        contentStyle={{ backgroundColor: '#2d2d2d', borderColor: '#444', color: '#fff' }}
                        itemStyle={{ fontSize: 14 }}
                    />
                    <Legend wrapperStyle={{ paddingTop: '10px' }} />
                    <Line yAxisId="left" type="monotone" dataKey={line1Key} stroke={line1Color} name={line1Name} dot={false} strokeWidth={2} activeDot={{ r: 6 }} />
                    <Line yAxisId="right" type="monotone" dataKey={line2Key} stroke={line2Color} name={line2Name} dot={false} strokeWidth={2} activeDot={{ r: 6 }} />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default Chart;
