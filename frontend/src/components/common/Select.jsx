import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import './Select.css'

export default function Select({ options, value, onChange, className = '', style = {} }) {
  const [open, setOpen] = useState(false)
  
  const selectedOption = options.find(o => o.value === value) || options[0]

  return (
    <div className={`custom-select-container ${className}`} style={style}>
      <div 
        className="custom-select-trigger" 
        onClick={() => setOpen(!open)}
      >
        <span>{selectedOption?.label}</span>
        <ChevronDown size={14} className={`custom-select-arrow ${open ? 'open' : ''}`} />
      </div>
      
      {open && (
        <>
          <div className="custom-select-backdrop" onClick={() => setOpen(false)} />
          <div className="custom-select-menu">
            {options.map((opt) => (
              <div
                key={opt.value}
                className={`custom-select-option ${value === opt.value ? 'selected' : ''}`}
                onClick={() => { onChange(opt.value); setOpen(false) }}
              >
                {opt.label}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
