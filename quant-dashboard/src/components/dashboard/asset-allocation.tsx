"use client";

import { useEffect, useState } from "react";
import { fundApi } from "@/lib/api";

interface AllocationItem {
  name: string;
  value: number;
  color: string;
}

const ALLOC_COLORS = [
  "#2563eb", "#16a34a", "#d97706", "#8b5cf6", "#ec4899",
  "#06b6d4", "#f97316", "#84cc16",
];

export function AssetAllocation() {
  const [data, setData] = useState<AllocationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalValue, setTotalValue] = useState(0);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fundApi.list();
        const funds = res.data || [];
        if (funds.length) {
          const total = funds.reduce((s, f) => s + f.shares * f.currentPrice, 0);
          setTotalValue(total);
          const items = funds.map((f, i) => ({
            name: f.name.length > 6 ? f.name.slice(0, 6) + "…" : f.name,
            value: Math.round(f.shares * f.currentPrice * 100) / 100,
            color: ALLOC_COLORS[i % ALLOC_COLORS.length],
          }));
          setData(items);
        } else {
          fallbackMock();
        }
      } catch {
        fallbackMock();
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function fallbackMock() {
    const mock = [
      { name: "易方达中小盘…", value: 10600, color: ALLOC_COLORS[0] },
      { name: "中欧医疗C", value: 2040, color: ALLOC_COLORS[1] },
      { name: "中欧时代先…", value: 5400, color: ALLOC_COLORS[2] },
      { name: "景顺长城新…", value: 3920, color: ALLOC_COLORS[3] },
      { name: "中欧医疗A", value: 4320, color: ALLOC_COLORS[4] },
    ];
    setData(mock);
    setTotalValue(mock.reduce((s, m) => s + m.value, 0));
  }

  const radius = 76;
  const strokeWidth = 30;
  const circumference = 2 * Math.PI * radius;
  const center = 100;

  // ── SVG donut segments with dashoffset ────────────────────
  // Default SVG circle starts at 3 o'clock. We rotate the <g>
  // by -90° around center so segments start at 12 o'clock.
  let cumulativeOffset = 0;
  const segments = data.map((d) => {
    const pct = data.length > 0 ? d.value / totalValue : 0;
    const segLen = pct * circumference;
    const offset = -cumulativeOffset;
    cumulativeOffset += segLen;
    return {
      ...d,
      pct,
      segLen,
      dasharray: `${Math.max(segLen, 1)} ${Math.max(circumference - segLen, 1)}`,
      dashoffset: offset,
    };
  });

  const hoveredSegment = hoveredIdx !== null ? segments[hoveredIdx] : null;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="text-xs text-text-tertiary font-medium mb-2">资产配置</div>

      {loading ? (
        <div className="flex items-center justify-center h-48 text-text-tertiary text-sm">
          加载中…
        </div>
      ) : (
        <div className="flex items-center gap-4">
          {/* ── Donut ────────────────────────────────────────── */}
          <div className="h-48 w-48 shrink-0 relative">
            <svg viewBox="0 0 200 200" className="w-full h-full">
              {/* Rotate -90° so 0° = 12 o'clock */}
              <g transform="rotate(-90 100 100)">
                {/* Subtle background ring */}
                <circle
                  cx={center}
                  cy={center}
                  r={radius}
                  fill="none"
                  stroke="var(--color-border-subtle)"
                  strokeWidth={strokeWidth}
                />
                {/* Segments */}
                {segments.map((s, i) => (
                  <circle
                    key={i}
                    cx={center}
                    cy={center}
                    r={radius}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={strokeWidth}
                    strokeDasharray={s.dasharray}
                    strokeDashoffset={s.dashoffset}
                    className="transition-opacity duration-200 cursor-pointer"
                    style={{
                      opacity:
                        hoveredIdx === null || hoveredIdx === i ? 1 : 0.25,
                    }}
                    onMouseEnter={() => setHoveredIdx(i)}
                    onMouseLeave={() => setHoveredIdx(null)}
                  />
                ))}
              </g>
            </svg>

            {/* Center text — changes on hover */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center">
                {hoveredSegment ? (
                  <>
                    <div className="text-lg font-semibold tabular-nums text-text-primary">
                      {(hoveredSegment.pct * 100).toFixed(1)}%
                    </div>
                    <div className="text-[10px] text-text-tertiary mt-0.5 max-w-[80px] truncate">
                      {hoveredSegment.name}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-lg font-semibold text-text-primary tabular-nums">
                      {data.length}
                    </div>
                    <div className="text-[10px] text-text-tertiary">持仓</div>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* ── Legend ────────────────────────────────────── */}
          <div className="flex-1 space-y-1.5">
            {segments.map((s, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-xs cursor-pointer transition-opacity duration-200"
                style={{
                  opacity:
                    hoveredIdx === null || hoveredIdx === i ? 1 : 0.35,
                }}
                onMouseEnter={() => setHoveredIdx(i)}
                onMouseLeave={() => setHoveredIdx(null)}
              >
                <span
                  className="w-2.5 h-2.5 rounded-sm shrink-0"
                  style={{ background: s.color }}
                />
                <span className="text-text-secondary flex-1 truncate">
                  {s.name}
                </span>
                <span className="text-text-primary tabular-nums font-medium">
                  {(s.pct * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
