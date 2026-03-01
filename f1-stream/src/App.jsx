import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

// ─── Data ────────────────────────────────────────────────────────────────────

const TEAM_COLORS = {
  MCL: '#ff8000', RBR: '#3671c6', MER: '#00d2be', FER: '#e8002d',
  AST: '#358c75', ALP: '#0093cc', HAA: '#b6babd', WIL: '#37bedd',
  SAU: '#52e252', RBT: '#6692ff',
}

const DRIVERS = [
  { pos:1,  num:63, code:'RUS', name:'RUSSELL',    team:'MER', gap:'LEADER', tyres:'S', tyreLaps:8,  drs:true  },
  { pos:2,  num:16, code:'LEC', name:'LECLERC',    team:'FER', gap:'+0.079', tyres:'S', tyreLaps:8,  drs:true  },
  { pos:3,  num:55, code:'SAI', name:'SAINZ',      team:'FER', gap:'+1.134', tyres:'M', tyreLaps:14, drs:false },
  { pos:4,  num:1,  code:'VER', name:'VERSTAPPEN', team:'RBR', gap:'+2.042', tyres:'M', tyreLaps:12, drs:false },
  { pos:5,  num:4,  code:'NOR', name:'NORRIS',     team:'MCL', gap:'+2.657', tyres:'S', tyreLaps:9,  drs:true  },
  { pos:6,  num:44, code:'HAM', name:'HAMILTON',   team:'MER', gap:'+4.891', tyres:'H', tyreLaps:22, drs:true  },
  { pos:7,  num:11, code:'PER', name:'PEREZ',      team:'RBR', gap:'+7.220', tyres:'H', tyreLaps:21, drs:false },
  { pos:8,  num:81, code:'PIA', name:'PIASTRI',    team:'MCL', gap:'+9.110', tyres:'M', tyreLaps:9,  drs:false },
  { pos:9,  num:14, code:'ALO', name:'ALONSO',     team:'AST', gap:'+12.33', tyres:'H', tyreLaps:28, drs:false },
  { pos:10, num:18, code:'STR', name:'STROLL',     team:'AST', gap:'+14.77', tyres:'H', tyreLaps:24, drs:false },
  { pos:11, num:10, code:'GAS', name:'GASLY',      team:'ALP', gap:'+16.20', tyres:'M', tyreLaps:11, drs:false },
  { pos:12, num:31, code:'OCO', name:'OCON',       team:'ALP', gap:'+18.88', tyres:'S', tyreLaps:6,  drs:false },
  { pos:13, num:20, code:'MAG', name:'MAGNUSSEN',  team:'HAA', gap:'+22.57', tyres:'M', tyreLaps:10, drs:false },
  { pos:14, num:23, code:'ALB', name:'ALBON',      team:'WIL', gap:'+25.01', tyres:'H', tyreLaps:19, drs:false },
  { pos:15, num:77, code:'BOT', name:'BOTTAS',     team:'SAU', gap:'+28.44', tyres:'H', tyreLaps:30, drs:false },
  { pos:16, num:24, code:'ZHO', name:'ZHOU',       team:'SAU', gap:'+31.22', tyres:'M', tyreLaps:15, drs:false },
  { pos:17, num:27, code:'HUL', name:'HULKENBERG', team:'HAA', gap:'+33.75', tyres:'H', tyreLaps:24, drs:false },
  { pos:18, num:2,  code:'SAR', name:'SARGEANT',   team:'WIL', gap:'+1 LAP', tyres:'M', tyreLaps:15, drs:false },
  { pos:19, num:22, code:'TSU', name:'TSUNODA',    team:'RBT', gap:'+1 LAP', tyres:'S', tyreLaps:7,  drs:false },
  { pos:20, num:3,  code:'RIC', name:'RICCIARDO',  team:'RBT', gap:'+1 LAP', tyres:'M', tyreLaps:12, drs:false },
]

const TYRE_COLORS = { S:'#e10600', M:'#ffd700', H:'#ffffff', I:'#39b54a', W:'#005aff' }

// ─── Hooks ───────────────────────────────────────────────────────────────────

function useTick(ms) {
  const [t, setT] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setT(p => p + 1), ms)
    return () => clearInterval(id)
  }, [ms])
  return t
}

function useLiveGaps() {
  const [gaps, setGaps] = useState(DRIVERS.map(d => d.gap))
  useEffect(() => {
    const id = setInterval(() => {
      setGaps(prev => prev.map((g, i) => {
        if (i === 0 || g.includes('LAP')) return g
        const n = parseFloat(g.replace('+', ''))
        if (isNaN(n)) return g
        return '+' + Math.max(0.001, n + (Math.random() - 0.49) * 0.05).toFixed(3)
      }))
    }, 700)
    return () => clearInterval(id)
  }, [])
  return gaps
}

function useTelemetry() {
  const [t, setT] = useState({ speed: 310, gear: 7, throttle: 98, brake: 0, rpm: 11400, drs: true })
  useEffect(() => {
    const id = setInterval(() => {
      setT(prev => {
        const spd = Math.max(80, Math.min(340, prev.speed + (Math.random() - 0.48) * 20))
        const g = spd > 290 ? 8 : spd > 240 ? 7 : spd > 195 ? 6 : spd > 155 ? 5 : spd > 115 ? 4 : 3
        const thr = spd > 250 ? 90 + Math.random() * 10 : Math.random() * 55
        const brk = spd < 180 ? Math.random() * 100 : 0
        return { speed: Math.round(spd), gear: g, throttle: Math.round(thr), brake: Math.round(brk), rpm: Math.round(7800 + (spd / 340) * 4200), drs: spd > 285 }
      })
    }, 220)
    return () => clearInterval(id)
  }, [])
  return t
}

function useLapTimer() {
  const [ms, setMs] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setMs(p => p + 100), 100)
    return () => clearInterval(id)
  }, [])
  const s = ms / 1000
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1).padStart(4, '0')
  return `${m}:${sec}`
}

// ─── Atoms ───────────────────────────────────────────────────────────────────

function TyreCircle({ type, size = 13 }) {
  const bg = TYRE_COLORS[type] || '#888'
  const textColor = (type === 'H' || type === 'M') ? '#000' : '#fff'
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', justifyContent:'center',
      width: size, height: size, borderRadius:'50%',
      background: bg, color: textColor,
      fontSize: size * 0.58, fontFamily:'var(--font-display)', fontWeight:900,
      flexShrink:0, lineHeight:1,
    }}>{type}</span>
  )
}

function LiveDot() {
  return (
    <span className="live-dot" style={{
      display:'inline-block', width:7, height:7, borderRadius:'50%',
      background:'var(--f1-red)', boxShadow:'0 0 6px var(--f1-red)',
      flexShrink:0,
    }} />
  )
}

function F1TVLogo({ size = 'sm' }) {
  const h = size === 'lg' ? 22 : 16
  return (
    <div style={{ display:'flex', alignItems:'center', gap:4 }}>
      <svg width={h * 1.8} height={h} viewBox="0 0 36 20" fill="none">
        <rect width="36" height="20" rx="2" fill="#e10600"/>
        <text x="3" y="15" fontFamily="'Barlow Condensed',sans-serif" fontWeight="900" fontSize="14" fill="white">F1</text>
      </svg>
      <span style={{
        fontFamily:'var(--font-display)', fontWeight:700,
        fontSize: size === 'lg' ? 13 : 10, color:'#fff', letterSpacing:'0.06em',
        lineHeight:1,
      }}>TV</span>
    </div>
  )
}

// ─── Timing Tower ─────────────────────────────────────────────────────────────

function TimingTower({ gaps }) {
  return (
    <div style={{
      width: '100%', height: '100%',
      background: 'rgba(8,8,8,0.96)',
      display:'flex', flexDirection:'column',
      overflow:'hidden',
    }}>
      {/* Header */}
      <div style={{
        background:'var(--f1-red)',
        padding:'3px 8px',
        display:'flex', alignItems:'center', justifyContent:'space-between',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:6 }}>
          <svg width="22" height="13" viewBox="0 0 22 13" fill="none">
            <rect width="22" height="13" rx="1" fill="white"/>
            <text x="2" y="10" fontFamily="'Barlow Condensed',sans-serif" fontWeight="900" fontSize="9" fill="#e10600">F1</text>
          </svg>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:9, color:'#fff', letterSpacing:'0.12em' }}>
            RACE
          </span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:4 }}>
          <LiveDot />
          <span style={{ fontFamily:'var(--font-display)', fontWeight:600, fontSize:8, color:'rgba(255,255,255,0.8)', letterSpacing:'0.1em' }}>
            LAP 41/57
          </span>
        </div>
      </div>

      {/* Column headers */}
      <div style={{
        display:'grid', gridTemplateColumns:'16px 24px 32px 1fr 28px',
        padding:'2px 6px', gap:3,
        background:'rgba(255,255,255,0.04)',
        borderBottom:'1px solid rgba(255,255,255,0.06)',
      }}>
        {['P','NO','DRV','GAP','TYR'].map(h => (
          <span key={h} style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:7.5, color:'#555', letterSpacing:'0.1em' }}>{h}</span>
        ))}
      </div>

      {/* Rows */}
      <div style={{ flex:1, overflowY:'hidden' }}>
        {DRIVERS.map((d, i) => {
          const isTop3 = i < 3
          const isHighlight = d.code === 'RUS'
          return (
            <div key={d.code} style={{
              display:'grid', gridTemplateColumns:'16px 24px 32px 1fr 28px',
              alignItems:'center', padding:'2.5px 6px', gap:3,
              background: isHighlight
                ? 'linear-gradient(90deg,rgba(0,210,190,0.12) 0%,transparent 100%)'
                : isTop3 ? 'rgba(255,255,255,0.02)' : 'transparent',
              borderLeft: isHighlight ? '2px solid var(--f1-green)' : isTop3 ? '2px solid var(--f1-red)' : '2px solid transparent',
              borderBottom:'1px solid rgba(255,255,255,0.03)',
            }}>
              <span style={{
                fontFamily:'var(--font-display)', fontWeight:800, fontSize:9,
                color: i === 0 ? 'var(--f1-red)' : '#666', textAlign:'center', lineHeight:1,
              }}>{d.pos}</span>
              <span style={{
                fontFamily:'var(--font-display)', fontWeight:800, fontSize:9.5,
                color: TEAM_COLORS[d.team], lineHeight:1,
              }}>{d.num}</span>
              <span style={{
                fontFamily:'var(--font-display)', fontWeight:700, fontSize:9.5,
                color: isHighlight ? 'var(--f1-green)' : '#ddd', letterSpacing:'0.02em', lineHeight:1,
              }}>{d.code}</span>
              <span style={{
                fontFamily:'var(--font-display)', fontWeight: i === 0 ? 700 : 500, fontSize:9,
                color: i === 0 ? '#fff' : gaps[i]?.startsWith('+0.') ? '#ffcc00' : '#999',
                letterSpacing:'0.01em', lineHeight:1,
                overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
              }}>{gaps[i]}</span>
              <TyreCircle type={d.tyres} size={11} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Main video HUD overlays ──────────────────────────────────────────────────

function MainHUD({ gaps, telem, lapTime }) {
  return (
    <>
      {/* Top-left: Race label */}
      <div style={{
        position:'absolute', top:8, left:8,
        display:'flex', alignItems:'center', gap:6, zIndex:10,
      }}>
        <svg width="28" height="18" viewBox="0 0 28 18" fill="none">
          <rect width="28" height="18" rx="2" fill="#e10600"/>
          <text x="2" y="13" fontFamily="'Barlow Condensed',sans-serif" fontWeight="900" fontSize="12" fill="white">F1</text>
        </svg>
        <span style={{
          fontFamily:'var(--font-display)', fontWeight:800, fontSize:11,
          color:'#fff', letterSpacing:'0.1em',
          textShadow:'0 1px 4px rgba(0,0,0,0.8)',
        }}>TV</span>
      </div>

      {/* Top-right of main: F1 TV watermark */}
      <div style={{
        position:'absolute', top:8, right:8, zIndex:10,
        display:'flex', alignItems:'center', gap:5,
      }}>
        <LiveDot />
        <F1TVLogo />
      </div>

      {/* Leader interval box (top-center) */}
      <IntervalBadge />

      {/* Driver telemetry bottom-left */}
      <DriverTelemetry telem={telem} lapTime={lapTime} />
    </>
  )
}

function IntervalBadge() {
  const [gap, setGap] = useState(0.079)
  useEffect(() => {
    const id = setInterval(() => {
      setGap(p => Math.max(0.001, p + (Math.random() - 0.48) * 0.04))
    }, 600)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{
      position:'absolute', top:8, left:'50%', transform:'translateX(-50%)',
      display:'flex', flexDirection:'column', alignItems:'center', zIndex:10,
    }}>
      {/* P1 chip */}
      <div style={{
        display:'flex', alignItems:'center', gap:6,
        background:'rgba(0,0,0,0.85)',
        border:'1px solid rgba(255,255,255,0.12)',
        borderRadius:3, padding:'3px 10px',
        backdropFilter:'blur(8px)',
      }}>
        <span style={{
          fontFamily:'var(--font-display)', fontWeight:900, fontSize:12,
          color:'var(--f1-red)', lineHeight:1,
        }}>1</span>
        <div style={{ width:1, height:12, background:'rgba(255,255,255,0.2)' }}/>
        <div style={{ display:'flex', flexDirection:'column' }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:8, color:'#888', letterSpacing:'0.08em', lineHeight:1 }}>
            RUSSELL
          </span>
          <span style={{
            fontFamily:'var(--font-display)', fontWeight:900, fontSize:14,
            color:'var(--f1-green)', letterSpacing:'0.04em', lineHeight:1, marginTop:1,
          }}>
            +{gap.toFixed(3)}
          </span>
        </div>
        <div style={{ width:1, height:12, background:'rgba(255,255,255,0.2)' }}/>
        <span style={{
          fontFamily:'var(--font-display)', fontWeight:900, fontSize:12,
          color:'#e8002d', lineHeight:1,
        }}>2</span>
        <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:11, color:'#ddd', lineHeight:1 }}>LEC</span>
      </div>
    </div>
  )
}

function DriverTelemetry({ telem, lapTime }) {
  const pctRpm = Math.min(100, ((telem.rpm - 7800) / 4200) * 100)
  const rpmColor = pctRpm > 80 ? '#e10600' : pctRpm > 60 ? '#ffd700' : '#00d2be'

  return (
    <div style={{
      position:'absolute', bottom:8, left:8,
      background:'rgba(0,0,0,0.82)',
      border:'1px solid rgba(255,255,255,0.1)',
      borderLeft:'3px solid #00d2be',
      borderRadius:3, overflow:'hidden',
      backdropFilter:'blur(10px)',
      zIndex:10, width:200,
    }}>
      {/* Driver name strip */}
      <div style={{
        background:'rgba(0,210,190,0.15)',
        padding:'3px 8px',
        display:'flex', alignItems:'center', justifyContent:'space-between',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:5 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:900, fontSize:14, color:'var(--f1-green)', lineHeight:1 }}>63</span>
          <div>
            <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:7.5, color:'#888', letterSpacing:'0.06em', lineHeight:1 }}>MERCEDES</div>
            <div style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:11, color:'#fff', letterSpacing:'0.06em', lineHeight:1 }}>RUSSELL</div>
          </div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:4 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:900, fontSize:16, color:'var(--f1-red)', lineHeight:1 }}>P1</span>
          <TyreCircle type="S" size={13}/>
        </div>
      </div>

      {/* Lap time row */}
      <div style={{ display:'flex', borderBottom:'1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ flex:1, padding:'4px 8px', borderRight:'1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:7.5, color:'#555', letterSpacing:'0.1em' }}>LAP TIME</div>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:13, color:'#fff', letterSpacing:'0.03em', lineHeight:1.1 }}>{lapTime}</div>
        </div>
        <div style={{ flex:1, padding:'4px 8px' }}>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:7.5, color:'#555', letterSpacing:'0.1em' }}>BEST</div>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:13, color:'var(--f1-purple)', letterSpacing:'0.03em', lineHeight:1.1 }}>1:33.207</div>
        </div>
      </div>

      {/* Speed + Gear */}
      <div style={{ display:'flex', borderBottom:'1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ flex:2, padding:'4px 8px', borderRight:'1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:7.5, color:'#555', letterSpacing:'0.1em' }}>SPEED</div>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:18, color:'#fff', lineHeight:1 }}>
            {telem.speed}<span style={{ fontSize:9, color:'#666', fontWeight:600 }}> km/h</span>
          </div>
        </div>
        <div style={{ flex:1, padding:'4px 8px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:7.5, color:'#555', letterSpacing:'0.1em' }}>GEAR</div>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:900, fontSize:22, color:'var(--f1-orange)', lineHeight:1 }}>{telem.gear}</div>
        </div>
        <div style={{ flex:1, padding:'4px 8px', borderLeft:'1px solid rgba(255,255,255,0.06)' }}>
          <div style={{
            padding:'2px 6px', borderRadius:2,
            background: telem.drs ? 'var(--f1-green)' : 'rgba(255,255,255,0.06)',
            fontFamily:'var(--font-display)', fontWeight:800, fontSize:8.5,
            color: telem.drs ? '#000' : '#444',
            letterSpacing:'0.08em', textAlign:'center',
            transition:'all 0.3s', marginTop:4,
          }}>DRS {telem.drs ? 'ON' : 'OFF'}</div>
        </div>
      </div>

      {/* Throttle / Brake bars */}
      <div style={{ padding:'4px 8px 5px', display:'flex', flexDirection:'column', gap:3 }}>
        <div style={{ display:'flex', alignItems:'center', gap:4 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:7.5, color:'var(--f1-green)', width:22, letterSpacing:'0.06em' }}>THR</span>
          <div style={{ flex:1, height:4, background:'rgba(255,255,255,0.08)', borderRadius:2, overflow:'hidden' }}>
            <div style={{ height:'100%', width:`${telem.throttle}%`, background:'var(--f1-green)', borderRadius:2, transition:'width 0.15s' }}/>
          </div>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:600, fontSize:8, color:'#555', width:22, textAlign:'right' }}>{telem.throttle}%</span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:4 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:7.5, color:'var(--f1-red)', width:22, letterSpacing:'0.06em' }}>BRK</span>
          <div style={{ flex:1, height:4, background:'rgba(255,255,255,0.08)', borderRadius:2, overflow:'hidden' }}>
            <div style={{ height:'100%', width:`${telem.brake}%`, background:'var(--f1-red)', borderRadius:2, transition:'width 0.15s' }}/>
          </div>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:600, fontSize:8, color:'#555', width:22, textAlign:'right' }}>{telem.brake}%</span>
        </div>
        {/* RPM */}
        <div style={{ display:'flex', alignItems:'center', gap:4, marginTop:1 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:7.5, color:'#555', width:22, letterSpacing:'0.06em' }}>RPM</span>
          <div style={{ flex:1, height:4, background:'rgba(255,255,255,0.08)', borderRadius:2, overflow:'hidden' }}>
            <div style={{ height:'100%', width:`${pctRpm}%`, background:rpmColor, borderRadius:2, transition:'width 0.15s, background 0.3s' }}/>
          </div>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:600, fontSize:7.5, color:'#555', width:22, textAlign:'right' }}>
            {Math.round(telem.rpm/1000 * 10) / 10}k
          </span>
        </div>
      </div>
    </div>
  )
}

// ─── Onboard Camera Panel ─────────────────────────────────────────────────────

function OnboardPanel({ driverNum, driverCode, team, tyreType, position, videoRef, startOffset = 0, label }) {
  const color = TEAM_COLORS[team] || '#fff'
  return (
    <div style={{
      position:'relative', width:'100%', height:'100%',
      background:'#0a0a0a', overflow:'hidden',
    }}>
      {/* Shared video (offset approach) */}
      <video
        ref={videoRef}
        src="/lando.mp4"
        autoPlay loop muted playsInline
        style={{ width:'100%', height:'100%', objectFit:'cover', filter:'brightness(0.95) saturate(1.1)' }}
      />
      {/* Dark overlay edges */}
      <div style={{
        position:'absolute', inset:0,
        background:'radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.55) 100%)',
        pointerEvents:'none',
      }}/>
      {/* Top-left corner chip */}
      <div style={{
        position:'absolute', top:5, left:5,
        display:'flex', alignItems:'center', gap:4,
        background:'rgba(0,0,0,0.75)',
        border:`1px solid ${color}`,
        borderRadius:2, padding:'2px 6px',
        backdropFilter:'blur(6px)',
      }}>
        <span style={{ fontFamily:'var(--font-display)', fontWeight:900, fontSize:10, color, lineHeight:1 }}>{driverNum}</span>
        <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:10, color:'#fff', lineHeight:1 }}>{driverCode}</span>
        <TyreCircle type={tyreType} size={11}/>
        <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:10, color:'var(--f1-red)', lineHeight:1 }}>P{position}</span>
      </div>
      {/* Top-right: F1 TV */}
      <div style={{
        position:'absolute', top:5, right:5,
        background:'rgba(0,0,0,0.6)',
        borderRadius:2, padding:'2px 5px',
      }}>
        <F1TVLogo size="sm"/>
      </div>
      {/* onboard label */}
      {label && (
        <div style={{
          position:'absolute', bottom:5, left:5,
          fontFamily:'var(--font-display)', fontWeight:600, fontSize:8,
          color:'rgba(255,255,255,0.5)', letterSpacing:'0.08em',
        }}>{label}</div>
      )}
    </div>
  )
}

// ─── Bottom Data Panel ────────────────────────────────────────────────────────

function DataPanel({ gaps }) {
  const tick = useTick(900)
  return (
    <div style={{
      width:'100%', height:'100%',
      background:'#070707',
      position:'relative', overflow:'hidden',
      display:'flex', flexDirection:'column',
    }}>
      {/* Header */}
      <div style={{
        background:'rgba(225,6,0,0.9)',
        padding:'3px 10px',
        display:'flex', alignItems:'center', justifyContent:'space-between',
        flexShrink:0,
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:6 }}>
          <svg width="22" height="13" viewBox="0 0 22 13" fill="none">
            <rect width="22" height="13" rx="1" fill="white"/>
            <text x="2" y="10" fontFamily="'Barlow Condensed',sans-serif" fontWeight="900" fontSize="9" fill="#e10600">F1</text>
          </svg>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:8, color:'#fff', letterSpacing:'0.15em' }}>
            FORMULA 1 LAS VEGAS GRAND PRIX 2024
          </span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:6 }}>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:600, fontSize:8, color:'rgba(255,255,255,0.7)', letterSpacing:'0.1em' }}>
            LAP 41 / 57
          </span>
          <F1TVLogo />
        </div>
      </div>

      {/* Timing grid */}
      <div style={{ flex:1, display:'grid', gridTemplateColumns:'1fr 1fr', gap:0, overflow:'hidden' }}>
        {/* Left col: positions 1-10 */}
        <div style={{ borderRight:'1px solid rgba(255,255,255,0.06)', overflow:'hidden' }}>
          {DRIVERS.slice(0, 10).map((d, i) => (
            <DataRow key={d.code} driver={d} gap={gaps[i]} tick={tick}/>
          ))}
        </div>
        {/* Right col: positions 11-20 */}
        <div style={{ overflow:'hidden' }}>
          {DRIVERS.slice(10, 20).map((d, i) => (
            <DataRow key={d.code} driver={d} gap={gaps[i + 10]} tick={tick}/>
          ))}
        </div>
      </div>

      {/* Bottom: mini track map placeholder */}
      <div style={{
        height:42, flexShrink:0,
        borderTop:'1px solid rgba(255,255,255,0.06)',
        display:'flex', alignItems:'center',
        padding:'0 12px', gap:12,
        background:'rgba(255,255,255,0.01)',
      }}>
        <TrackMapMini />
        <div style={{ flex:1 }}>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:400, fontSize:8, color:'#555', letterSpacing:'0.08em' }}>FASTEST LAP</div>
          <div style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:12, color:'var(--f1-purple)', letterSpacing:'0.04em' }}>
            RUS — 1:33.207 — LAP 41
          </div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:4 }}>
          <div style={{ width:6, height:6, borderRadius:'50%', background:'var(--f1-green)' }}/>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:9, color:'var(--f1-green)', letterSpacing:'0.1em' }}>GREEN FLAG</span>
        </div>
      </div>
    </div>
  )
}

function DataRow({ driver, gap, tick }) {
  const isTop3 = driver.pos <= 3
  const color = TEAM_COLORS[driver.team] || '#fff'
  // subtle highlight flicker for live feel
  const isUpdated = tick % 7 === driver.pos % 7

  return (
    <div style={{
      display:'grid', gridTemplateColumns:'14px 18px 28px 1fr 22px',
      alignItems:'center', padding:'1.5px 8px', gap:3,
      borderBottom:'1px solid rgba(255,255,255,0.03)',
      background: isUpdated ? 'rgba(255,255,255,0.015)' : 'transparent',
      transition:'background 0.3s',
    }}>
      <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:8.5, color: isTop3 ? 'var(--f1-red)' : '#555', textAlign:'center', lineHeight:1 }}>
        {driver.pos}
      </span>
      <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:9, color, lineHeight:1 }}>
        {driver.num}
      </span>
      <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:9, color:'#ccc', lineHeight:1 }}>
        {driver.code}
      </span>
      <span style={{
        fontFamily:'var(--font-display)', fontWeight: driver.pos === 1 ? 700 : 500, fontSize:8.5,
        color: driver.pos === 1 ? '#fff' : '#888', lineHeight:1,
        overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
      }}>
        {gap}
      </span>
      <TyreCircle type={driver.tyres} size={9}/>
    </div>
  )
}

function TrackMapMini() {
  // Simple SVG track outline (stylized Las Vegas street circuit)
  return (
    <svg width="80" height="34" viewBox="0 0 80 34" fill="none">
      <rect x="1" y="1" width="78" height="32" rx="4" stroke="#333" strokeWidth="1" fill="none"/>
      <path d="M10 28 L10 6 Q10 4 12 4 L68 4 Q70 4 70 6 L70 14 Q70 16 68 16 L30 16 Q28 16 28 18 L28 28 Q28 30 26 30 L12 30 Q10 30 10 28Z"
        stroke="#555" strokeWidth="1.5" fill="none" strokeLinejoin="round"/>
      {/* cars dots */}
      <circle cx="12" cy="14" r="2" fill="#00d2be"/>
      <circle cx="12" cy="10" r="2" fill="#e8002d"/>
      <circle cx="14" cy="6" r="2" fill="#e8002d"/>
      <circle cx="20" cy="4" r="2" fill="#3671c6"/>
      <circle cx="28" cy="4" r="2" fill="#ff8000"/>
    </svg>
  )
}

// ─── TV Bezel ────────────────────────────────────────────────────────────────

function TVBezel({ children }) {
  return (
    <div style={{
      position:'relative',
      width:'min(98vw, calc(98vh * 1.85))',
      aspectRatio:'16/9',
      background:'linear-gradient(145deg, #1a2a3a, #0d1820, #1a2a3a)',
      borderRadius:'12px',
      boxShadow:`
        0 0 0 2px #2a4a6a,
        0 0 0 4px rgba(0,180,255,0.3),
        0 0 40px rgba(0,180,255,0.2),
        0 0 80px rgba(0,120,200,0.15),
        0 30px 60px rgba(0,0,0,0.8),
        inset 0 1px 0 rgba(255,255,255,0.08)
      `,
      overflow:'visible',
    }}>
      {/* Bezel inner glow line */}
      <div style={{
        position:'absolute', inset:2,
        borderRadius:10,
        border:'1px solid rgba(0,200,255,0.15)',
        pointerEvents:'none', zIndex:100,
      }}/>

      {/* Screen area */}
      <div style={{
        position:'absolute', inset:'3%',
        borderRadius:6,
        overflow:'hidden',
        background:'#000',
        boxShadow:'inset 0 0 30px rgba(0,0,0,0.8)',
      }}>
        {children}
      </div>

      {/* Feet */}
      <div style={{
        position:'absolute', bottom:'-32px', left:'50%', transform:'translateX(-50%)',
        display:'flex', gap:60, alignItems:'flex-end',
      }}>
        {[0, 1].map(i => (
          <div key={i} style={{
            width:40, height:28,
            background:'linear-gradient(to bottom, #1a2a3a, #0d1820)',
            borderRadius:'0 0 8px 8px',
            boxShadow:'0 0 10px rgba(0,180,255,0.3), 0 4px 12px rgba(0,0,0,0.5)',
            border:'1px solid rgba(0,150,220,0.4)',
            borderTop:'none',
          }}/>
        ))}
      </div>

      {/* Base stand */}
      <div style={{
        position:'absolute', bottom:'-46px', left:'50%', transform:'translateX(-50%)',
        width:160, height:14,
        background:'linear-gradient(to bottom, #1a2a3a, #0d1820)',
        borderRadius:'0 0 6px 6px',
        boxShadow:'0 0 20px rgba(0,180,255,0.2), 0 4px 16px rgba(0,0,0,0.6)',
        border:'1px solid rgba(0,150,220,0.3)',
        borderTop:'none',
      }}/>
    </div>
  )
}

// ─── Control Bar ─────────────────────────────────────────────────────────────

function ControlBar({ videoRef, playing, setPlaying }) {
  const [vol, setVol] = useState(0.7)
  const [muted, setMuted] = useState(false)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const update = () => setProgress(v.duration ? (v.currentTime / v.duration) * 100 : 0)
    v.addEventListener('timeupdate', update)
    return () => v.removeEventListener('timeupdate', update)
  }, [videoRef])

  const togglePlay = () => {
    const v = videoRef.current; if (!v) return
    if (playing) { v.pause(); setPlaying(false) }
    else { v.play().catch(()=>{}); setPlaying(true) }
  }

  const changeVol = e => {
    const val = parseFloat(e.target.value)
    setVol(val)
    if (videoRef.current) videoRef.current.volume = val
    setMuted(val === 0)
  }

  const seek = e => {
    const v = videoRef.current; if (!v) return
    const pct = parseFloat(e.target.value)
    v.currentTime = (pct / 100) * v.duration
    setProgress(pct)
  }

  const toggleMute = () => {
    const v = videoRef.current; if (!v) return
    const m = !muted; setMuted(m); v.muted = m
  }

  return (
    <div style={{
      position:'absolute', bottom:0, left:0, right:0,
      background:'linear-gradient(0deg, rgba(0,0,0,0.92) 0%, rgba(0,0,0,0.6) 70%, transparent 100%)',
      padding:'6px 12px 4px', zIndex:50,
      display:'flex', flexDirection:'column', gap:4,
    }}>
      <input type="range" min={0} max={100} step={0.1} value={progress} onChange={seek}
        style={{ width:'100%', height:3, cursor:'pointer', accentColor:'#e10600' }}
      />
      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
        <button onClick={togglePlay} style={{
          fontFamily:'monospace', fontSize:16, color:'#fff', lineHeight:1, cursor:'pointer',
        }}>
          {playing ? '⏸' : '▶'}
        </button>
        <button onClick={toggleMute} style={{ fontSize:14, color:'#fff', lineHeight:1, cursor:'pointer' }}>
          {muted || vol === 0 ? '🔇' : vol > 0.5 ? '🔊' : '🔉'}
        </button>
        <input type="range" min={0} max={1} step={0.01} value={muted ? 0 : vol} onChange={changeVol}
          style={{ width:60, height:3, accentColor:'#fff', cursor:'pointer' }}
        />
        <div style={{ flex:1 }}/>
        <div style={{ display:'flex', alignItems:'center', gap:5 }}>
          <LiveDot/>
          <span style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:10, color:'var(--f1-red)', letterSpacing:'0.1em' }}>LIVE</span>
        </div>
        <button style={{ fontSize:14, color:'#fff', lineHeight:1, cursor:'pointer' }}>⛶</button>
      </div>
    </div>
  )
}

// ─── Ticker ───────────────────────────────────────────────────────────────────

function TickerBar() {
  const messages = [
    '⚡ FASTEST LAP: RUSSELL — 1:33.207 — LAP 41',
    '🏁 RUSSELL EXTENDS LEAD OVER LECLERC',
    '🔧 VERSTAPPEN PITTED LAP 39 — HARD TYRE',
    '📻 LECLERC: "WE NEED TO PUSH NOW OR NEVER"',
    '🔴 DRS DETECTION ZONE — TURN 1',
    '⚡ NORRIS FASTEST IN S2 — PURPLE SECTOR',
  ]
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setIdx(p => (p + 1) % messages.length), 6000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{
      position:'absolute', bottom:0, left:0, right:0, height:22,
      background:'rgba(0,0,0,0.9)',
      borderTop:'2px solid var(--f1-red)',
      display:'flex', alignItems:'center', overflow:'hidden',
      zIndex:20,
    }}>
      <div style={{
        flexShrink:0,
        background:'var(--f1-red)',
        height:'100%', display:'flex', alignItems:'center',
        padding:'0 10px',
      }}>
        <span style={{ fontFamily:'var(--font-display)', fontWeight:800, fontSize:9.5, color:'#fff', letterSpacing:'0.12em', whiteSpace:'nowrap' }}>
          F1 LIVE
        </span>
      </div>
      <div style={{ flex:1, padding:'0 12px', overflow:'hidden' }}>
        <span style={{
          fontFamily:'var(--font-display)', fontWeight:600, fontSize:10,
          color:'#fff', letterSpacing:'0.04em', whiteSpace:'nowrap',
        }}>
          {messages[idx]}
        </span>
      </div>
    </div>
  )
}

// ─── Layout ───────────────────────────────────────────────────────────────────

export default function App() {
  const mainVideoRef = useRef(null)
  const ob1Ref = useRef(null)
  const ob2Ref = useRef(null)
  const [playing, setPlaying] = useState(false)
  const gaps = useLiveGaps()
  const telem = useTelemetry()
  const lapTime = useLapTimer()

  // Keep onboard streams behind the main feed by a fixed delay.
  // Every 500ms we check the main video's currentTime and nudge the
  // onboards if they drift more than 0.3s from their target offset.
  const OB1_DELAY = 6   // seconds behind main
  const OB2_DELAY = 12  // seconds behind main

  useEffect(() => {
    // Auto-play onboards muted
    ob1Ref.current?.play().catch(() => {})
    ob2Ref.current?.play().catch(() => {})

    const sync = () => {
      const main = mainVideoRef.current
      const ob1  = ob1Ref.current
      const ob2  = ob2Ref.current
      if (!main || !ob1 || !ob2 || !main.duration) return

      const dur = main.duration
      const t   = main.currentTime

      // Wrap-around safe target times
      const t1 = ((t - OB1_DELAY) % dur + dur) % dur
      const t2 = ((t - OB2_DELAY) % dur + dur) % dur

      if (Math.abs(ob1.currentTime - t1) > 0.4) ob1.currentTime = t1
      if (Math.abs(ob2.currentTime - t2) > 0.4) ob2.currentTime = t2
    }

    const id = setInterval(sync, 500)
    return () => clearInterval(id)
  }, [])

  return (
    <TVBezel>
      {/*
        Layout matches screenshot:
        Left 62%: Main feed + timing tower overlay
        Right 38%: split into 3 rows (2 onboards top + data panel bottom)
      */}
      <div style={{
        width:'100%', height:'100%',
        display:'grid',
        gridTemplateColumns:'62% 38%',
        gridTemplateRows:'1fr',
        background:'#000',
      }}>

        {/* ── LEFT: Main Video Feed ─────────────────────────────── */}
        <div style={{ position:'relative', overflow:'hidden' }}>
          {/* Main video */}
          <video
            ref={mainVideoRef}
            src="/lando.mp4"
            loop playsInline muted
            onClick={() => {
              const v = mainVideoRef.current; if (!v) return
              if (playing) { v.pause(); setPlaying(false) }
              else { v.play().catch(()=>{}); setPlaying(true) }
            }}
            style={{ width:'100%', height:'100%', objectFit:'cover', cursor:'pointer' }}
          />

          {/* subtle vignette */}
          <div style={{
            position:'absolute', inset:0, pointerEvents:'none',
            background:'radial-gradient(ellipse at 60% 50%, transparent 40%, rgba(0,0,0,0.45) 100%)',
          }}/>

          {/* Right-side gradient for panel readability */}
          <div style={{
            position:'absolute', top:0, right:0, bottom:0, width:4,
            background:'rgba(0,0,0,0.6)', pointerEvents:'none',
          }}/>

          {/* Timing tower overlay (left column) */}
          <div style={{
            position:'absolute', top:0, left:0, bottom:22, width:130,
            background:'rgba(0,0,0,0.12)',
          }}>
            <TimingTower gaps={gaps}/>
          </div>

          {/* Main HUD overlays */}
          <MainHUD gaps={gaps} telem={telem} lapTime={lapTime}/>

          {/* Bottom ticker */}
          <TickerBar/>

          {/* Video controls (hover area) */}
          <ControlBar videoRef={mainVideoRef} playing={playing} setPlaying={setPlaying}/>
        </div>

        {/* ── RIGHT: Multi-panel column ────────────────────────── */}
        <div style={{
          display:'grid',
          gridTemplateRows:'1fr 1fr 42%',
          borderLeft:'1px solid #111',
          overflow:'hidden',
        }}>

          {/* Onboard 1 — LEC */}
          <div style={{ borderBottom:'1px solid #111', overflow:'hidden' }}>
            <OnboardPanel
              videoRef={ob1Ref}
              driverNum={16} driverCode="LEC" team="FER" tyreType="S" position={2}
              label="ONBOARD · LECLERC"
            />
          </div>

          {/* Onboard 2 — VER */}
          <div style={{ borderBottom:'1px solid #111', overflow:'hidden' }}>
            <OnboardPanel
              videoRef={ob2Ref}
              driverNum={1} driverCode="VER" team="RBR" tyreType="M" position={4}
              label="ONBOARD · VERSTAPPEN"
            />
          </div>

          {/* Bottom: Full data / timing panel */}
          <div style={{ overflow:'hidden' }}>
            <DataPanel gaps={gaps}/>
          </div>
        </div>
      </div>
    </TVBezel>
  )
}
