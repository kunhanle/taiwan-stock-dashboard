import { useState } from 'react'
import axios from 'axios'
import { Activity, Search, AlertCircle, Plus, Trash2, Calendar } from 'lucide-react'
import Chart from './components/Chart'

function App() {
  const [stockIds, setStockIds] = useState([''])
  const [metal, setMetal] = useState('Copper')

  // Default date range: Past 2 years
  const today = new Date().toISOString().split('T')[0]
  const twoYearsAgo = new Date(new Date().setFullYear(new Date().getFullYear() - 2)).toISOString().split('T')[0]

  const [startDate, setStartDate] = useState(twoYearsAgo)
  const [endDate, setEndDate] = useState(today)

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const metals = [
    'Gold', 'Silver', 'Copper', 'Platinum', 'Palladium',
    'Aluminium', 'Nickel', 'Zinc'
  ]

  const addStockInput = () => {
    setStockIds([...stockIds, ''])
  }

  const removeStockInput = (index) => {
    const newStockIds = stockIds.filter((_, i) => i !== index)
    setStockIds(newStockIds.length ? newStockIds : [''])
  }

  const updateStockId = (index, value) => {
    const newStockIds = [...stockIds]
    newStockIds[index] = value
    setStockIds(newStockIds)
  }

  const handleAnalyze = async (e) => {
    e.preventDefault()
    const validStockIds = stockIds.filter(id => id.trim() !== '')
    if (validStockIds.length === 0) {
      setError('Please enter at least one stock ID')
      return
    }

    setLoading(true)
    setError('')
    setResult(null)

    try {
      const response = await axios.post('/api/analyze', {
        stock_ids: validStockIds,
        metal: metal,
        start_date: startDate,
        end_date: endDate
      })
      setResult(response.data)
    } catch (err) {
      console.error(err)
      if (err.response) {
        // Server responded with a status code outside 2xx
        setError(`Server Error (${err.response.status}): ${err.response.data?.error || err.message}`)
      } else if (err.request) {
        // Request was made but no response received
        setError('Network Error: No response received from server. Check backend connection.')
      } else {
        // Something happened in setting up the request
        setError(`Request Error: ${err.message}`)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white font-sans p-6">
      {/* Full width container as requested */}
      <div className="w-full max-w-[95%] mx-auto">
        <header className="mb-8 flex flex-col items-center">
          <h1 className="text-4xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent flex items-center gap-3">
            <Activity className="w-10 h-10 text-emerald-400" />
            Stock-Metal Correlation
          </h1>
          <p className="text-gray-400 mt-2">Analyze relationship between global stocks and commodity prices</p>
        </header>

        <div className="bg-gray-800 p-6 rounded-xl shadow-xl mb-8 border border-gray-700">
          <form onSubmit={handleAnalyze} className="space-y-6">

            <div className="flex flex-col lg:flex-row gap-6">
              {/* Stocks Section */}
              <div className="flex-1 space-y-3">
                <label className="block text-sm font-medium text-gray-400">Stock IDs</label>
                {stockIds.map((id, index) => (
                  <div key={index} className="flex gap-2">
                    <input
                      type="text"
                      placeholder="e.g. NIKL, 1605.TW"
                      value={id}
                      onChange={(e) => updateStockId(index, e.target.value)}
                      className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 focus:ring-2 focus:ring-emerald-500 focus:outline-none placeholder-gray-500"
                    />
                    {stockIds.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeStockInput(index)}
                        className="p-2 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-5 h-5" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={addStockInput}
                  className="text-sm text-emerald-400 hover:text-emerald-300 flex items-center gap-1 font-medium"
                >
                  <Plus className="w-4 h-4" /> Add Stock
                </button>
              </div>

              {/* Settings Section */}
              <div className="lg:w-1/3 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Metal</label>
                  <div className="flex gap-2">
                    <select
                      value={metal}
                      onChange={(e) => setMetal(e.target.value)}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 focus:ring-2 focus:ring-emerald-500 focus:outline-none"
                    >
                      <option value="">-- Select Metal --</option>
                      {metals.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                    {metal && (
                      <button
                        type="button"
                        onClick={() => setMetal('')}
                        className="p-2 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded-lg transition-colors"
                        title="Remove Metal"
                      >
                        <Trash2 className="w-5 h-5" />
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1 flex items-center gap-1">
                      <Calendar className="w-3 h-3" /> Start Date
                    </label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1 flex items-center gap-1">
                      <Calendar className="w-3 h-3" /> End Date
                    </label>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 focus:outline-none"
                    />
                  </div>
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-bold text-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
            >
              {loading ? 'Analyzing...' : <><Search className="w-5 h-5" /> Analyze Data</>}
            </button>
          </form>
        </div>

        {error && (
          <div className="bg-red-900/50 border border-red-700 text-red-200 p-4 rounded-lg mb-8 flex items-center gap-2">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-12 animate-in fade-in slide-in-from-bottom-4 duration-700">

            {/* 1. Stock vs Stock Comparison (If applicable) */}
            {result.stock_vs_stock && result.stock_vs_stock.length > 0 && (
              <section>
                <h2 className="text-2xl font-bold mb-4 text-gray-200 border-b border-gray-700 pb-2">Stock Comparison</h2>
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
                  {result.stock_vs_stock.map((item, idx) => (
                    <div key={idx} className="space-y-4">
                      <div className="bg-gray-800/50 p-4 rounded-lg border border-gray-700 flex justify-between items-center">
                        <span className="font-semibold text-gray-300">{item.stock1} vs {item.stock2}</span>
                        <span className={`text-xl font-bold px-3 py-1 rounded bg-gray-900 ${item.correlation > 0.5 ? 'text-emerald-400' : item.correlation < -0.5 ? 'text-red-400' : 'text-yellow-400'}`}>
                          Corr: {item.correlation.toFixed(4)}
                        </span>
                      </div>
                      <Chart
                        title={`${item.stock1} vs ${item.stock2}`}
                        data={item.data}
                        line1Key="price1"
                        line2Key="price2"
                        line1Name={item.stock1}
                        line2Name={item.stock2}
                        line1Color="#60a5fa" // Blue
                        line2Color="#f472b6" // Pink
                      />
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* 2. Stock vs Metal Comparisons (Only if Metal is selected) */}
            <section>
              <h2 className="text-2xl font-bold mb-4 text-gray-200 border-b border-gray-700 pb-2">
                {metal ? `Stock vs Metal (${metal})` : 'Stock Price History'}
              </h2>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
                {result.stock_results.map((item, idx) => (
                  <div key={idx} className="space-y-4">
                    {item.error ? (
                      <div className="bg-red-900/20 border border-red-700/50 p-4 rounded-lg text-red-300">
                        Error for {item.stock_id}: {item.error}
                      </div>
                    ) : (
                      <>
                        <div className="bg-gray-800/50 p-4 rounded-lg border border-gray-700 flex justify-between items-center">
                          <div>
                            <span className="text-gray-400 text-sm block">Stock</span>
                            <span className="font-semibold text-lg">{item.stock_name} <span className="text-gray-500 text-sm">({item.stock_id})</span></span>
                          </div>
                          {item.correlation !== null && ( // Only show correlation if metal is selected and correlation exists
                            <div className={`text-center px-4 py-2 rounded bg-gray-900 border border-gray-700`}>
                              <div className="text-xs text-gray-400">Correlation</div>
                              <div className={`text-xl font-bold ${item.correlation > 0.5 ? 'text-emerald-400' : item.correlation < -0.5 ? 'text-red-400' : 'text-yellow-400'}`}>
                                {item.correlation.toFixed(4)}
                              </div>
                            </div>
                          )}
                        </div>
                        <Chart
                          title={metal ? `${item.stock_name} vs ${metal}` : `${item.stock_name} Price`}
                          data={item.data}
                          line1Key="stock_price"
                          line2Key={metal ? "metal_price" : null} // Only pass metal_price if metal is selected
                          line1Name={item.stock_name}
                          line2Name={metal || ""} // Pass metal name or empty string
                          line1Color="#8884d8"
                          line2Color="#82ca9d"
                        />
                      </>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </div>
        )
        }
      </div >
    </div >
  )
}

export default App
