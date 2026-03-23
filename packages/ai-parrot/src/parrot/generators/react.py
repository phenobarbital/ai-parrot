from typing import Type, List
from pydantic import BaseModel, Field
from .base import WebAppGenerator


class ReactApp(BaseModel):
    """Pydantic schema for React application output."""
    code: str = Field(description="Complete React component code")
    component_name: str = Field(description="Main component name")
    description: str = Field(description="App description")
    dependencies: List[str] = Field(
        description="External dependencies used",
        default_factory=lambda: ["react", "recharts", "lucide-react"]
    )
    features: List[str] = Field(description="Key features implemented")


class ReactGenerator(WebAppGenerator):
    """Generator for React applications."""

    def get_system_prompt(self) -> str:
        return """You are a senior React developer building modern, responsive web applications.

**User Requirements:**
{user_description}

**Technical Stack:**
- React 18+ with Hooks (useState, useEffect, useReducer, useMemo, useCallback)
- Tailwind CSS for ALL styling (no inline styles)
- Recharts for charts and data visualization
- Lucide React for icons
- Mock data only (no external API calls)

**Code Quality Standards:**
- Functional components only (no class components)
- Proper prop destructuring and validation
- Clean, modular component structure
- Responsive design using Tailwind's responsive classes
- Accessibility: ARIA labels, semantic HTML, keyboard navigation
- Performance: useMemo for expensive computations, useCallback for event handlers

**Styling Requirements:**
- Use ONLY Tailwind utility classes
- Consistent color palette (blue-600 primary, gray-50 backgrounds)
- Proper spacing scale (p-4, p-6, etc.)
- Smooth transitions (transition-all duration-300)
- Hover states for interactive elements
- Mobile-first responsive design

**Component Structure:**
1. Import statements at top
2. Component definition with clear function name
3. State declarations grouped together
4. Helper functions
5. useEffect hooks
6. JSX return statement
7. Default export

**Best Practices:**
- Break large components into smaller ones
- Keep components under 200 lines
- Use meaningful variable names
- Add comments for complex logic
- Include loading and error states
- Implement proper form validation

**Example Quality Standard:**
{high_quality_example}

Generate a complete, self-contained React component as a default export."""

    def get_output_schema(self) -> Type[BaseModel]:
        return ReactApp

    def get_examples(self) -> str:
        return '''
import React, { useState, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { TrendingUp, Download, Filter } from 'lucide-react';

const Dashboard = () => {
  // Mock data
  const [data] = useState([
    { name: 'Jan', revenue: 4000, expenses: 2400 },
    { name: 'Feb', revenue: 3000, expenses: 1398 },
    { name: 'Mar', revenue: 2000, expenses: 9800 },
    { name: 'Apr', revenue: 2780, expenses: 3908 },
    { name: 'May', revenue: 1890, expenses: 4800 },
    { name: 'Jun', revenue: 2390, expenses: 3800 }
  ]);

  const [filterActive, setFilterActive] = useState(false);

  // Compute metrics
  const metrics = useMemo(() => ({
    totalRevenue: data.reduce((sum, item) => sum + item.revenue, 0),
    totalExpenses: data.reduce((sum, item) => sum + item.expenses, 0),
    avgRevenue: data.reduce((sum, item) => sum + item.revenue, 0) / data.length
  }), [data]);

  const handleExport = () => {
    const csv = [
      'Month,Revenue,Expenses',
      ...data.map(d => `${d.name},${d.revenue},${d.expenses}`)
    ].join('\\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'data.csv';
    a.click();
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <TrendingUp className="text-blue-600" size={32} />
              <div>
                <h1 className="text-3xl font-bold text-gray-900">
                  Financial Dashboard
                </h1>
                <p className="text-gray-600">Track your revenue and expenses</p>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setFilterActive(!filterActive)}
                className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                aria-label="Toggle filters"
              >
                <Filter size={18} />
                Filters
              </button>
              <button
                onClick={handleExport}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-lg transition-colors"
                aria-label="Export data"
              >
                <Download size={18} />
                Export
              </button>
            </div>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4">
              <div className="text-sm text-blue-600 font-medium mb-1">
                Total Revenue
              </div>
              <div className="text-2xl font-bold text-blue-900">
                ${metrics.totalRevenue.toLocaleString()}
              </div>
            </div>
            <div className="bg-gradient-to-br from-red-50 to-red-100 rounded-lg p-4">
              <div className="text-sm text-red-600 font-medium mb-1">
                Total Expenses
              </div>
              <div className="text-2xl font-bold text-red-900">
                ${metrics.totalExpenses.toLocaleString()}
              </div>
            </div>
            <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4">
              <div className="text-sm text-green-600 font-medium mb-1">
                Avg Revenue
              </div>
              <div className="text-2xl font-bold text-green-900">
                ${Math.round(metrics.avgRevenue).toLocaleString()}
              </div>
            </div>
          </div>
        </div>

        {/* Chart */}
        <div className="bg-white rounded-lg shadow-lg p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">
            Monthly Comparison
          </h2>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="revenue" fill="#3b82f6" name="Revenue" />
              <Bar dataKey="expenses" fill="#ef4444" name="Expenses" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
'''

    def _get_file_extension(self) -> str:
        return '.jsx'
