"use client";

import { useEffect, useState } from "react";
import { timeApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Clock, CalendarDays, AlertTriangle, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface KnowledgeSection {
  id: string;
  title: string;
  icon: string;
  rules: { title: string; items: string[]; warning?: string }[];
}

export default function TimeRulesPage() {
  const [sections, setSections] = useState<KnowledgeSection[]>([]);
  const [currentStatus, setCurrentStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [kb, st] = await Promise.all([
          timeApi.knowledge(),
          timeApi.status(),
        ]);
        if (kb?.sections) setSections(kb.sections);
        if (st) setCurrentStatus(st);
      } catch {}
      // 即使后端挂了也展示内置数据
      setSections(FALLBACK_SECTIONS);
      setLoading(false);
    }
    load();
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">时间知识库</h1>
        <p className="text-sm text-text-tertiary mt-0.5">基金买卖必须卡死的所有时间节点</p>
      </div>

      {/* 实时状态 */}
      {currentStatus && (
        <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-text-tertiary">当前交易状态</span>
            <Badge variant="outline" className={cn("h-6 text-xs", currentStatus.isBefore1500 && currentStatus.isTradingDay ? "text-positive border-positive/30" : "text-text-tertiary")}>
              {currentStatus.isBefore1500 ? "15:00前" : "15:00后"}
            </Badge>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><span className="text-text-tertiary text-xs">日期</span><p className="tabular-nums text-text-primary font-medium">{currentStatus.date}</p></div>
            <div><span className="text-text-tertiary text-xs">交易日</span><p className={cn("font-medium", currentStatus.isTradingDay ? "text-positive" : "text-text-tertiary")}>{currentStatus.isTradingDay ? "✅ 是" : "❌ 否"}</p></div>
            <div><span className="text-text-tertiary text-xs">状态</span><p className="text-text-primary font-medium">{currentStatus.statusLabel || currentStatus.status}</p></div>
            <div><span className="text-text-tertiary text-xs">ETF交易</span><p className={cn("font-medium", currentStatus.isETFTradingTime ? "text-positive" : "text-text-tertiary")}>{currentStatus.isETFTradingTime ? "🟢 盘中" : "⏸️ 非交易时段"}</p></div>
          </div>
          {currentStatus.holidayStrategy?.warnings?.length > 0 && (
            <div className="mt-2 p-2 rounded-lg bg-warning/5 border border-warning/20 flex items-start gap-2 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{currentStatus.holidayStrategy.warnings[0]}</span>
            </div>
          )}
        </div>
      )}

      {/* 知识库章节 */}
      <div className="space-y-3">
        {sections.map((section) => (
          <div key={section.id} className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg">{section.icon}</span>
              <h2 className="text-sm font-semibold text-text-primary">{section.title}</h2>
            </div>
            <div className="space-y-3">
              {section.rules.map((rule, ri) => (
                <div key={ri}>
                  <h3 className="text-xs font-medium text-text-secondary mb-1.5">{rule.title}</h3>
                  <ul className="space-y-1">
                    {rule.items.map((item, ii) => (
                      <li key={ii} className="text-xs text-text-primary pl-3 relative leading-relaxed">
                        <span className="absolute left-0 top-[5px] w-1 h-1 rounded-full bg-text-tertiary" />
                        {item}
                      </li>
                    ))}
                  </ul>
                  {rule.warning && (
                    <div className="mt-1.5 p-1.5 rounded bg-warning/5 border border-warning/20 text-xs text-warning flex items-start gap-1.5">
                      <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                      <span>{rule.warning}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const FALLBACK_SECTIONS: KnowledgeSection[] = [
  {
    id: "golden_rules", title: "七、极简盈利4条", icon: "🏆",
    rules: [{
      title: "记住这4条就够了",
      items: [
        "所有买卖操作交易日 14:30-14:55 完成，卡死15点分界线",
        "短线务必持有满7天再卖，规避1.5%高额赎回费",
        "长假操作一律在节前最后一日15点前完成",
        "QDII看海外收盘时差，利好隔夜消息次日早盘立刻操作",
      ],
    }],
  },
  {
    id: "cutoff_1500", title: "一、场外基金核心分界线 15:00", icon: "⏰",
    rules: [
      {
        title: "买入：15:00前 vs 后",
        items: [
          "T日15:00前买入 → 当天收盘净值成交，T+1日确认份额",
          "T日15:00后买入 → 顺延至T+1交易日净值成交，T+2日才计息",
          "周末/节假日下单 → 全部归节后第一个交易日T日净值",
        ],
        warning: "周五15点后买入，按下周一净值，周末两天上涨完全吃不到",
      },
      {
        title: "卖出：15:00前 vs 后",
        items: [
          "T日15:00前赎回 → 锁定当日净值，T+1起不再承担涨跌",
          "T日15:00后赎回 → 按次日净值结算，多扛一天波动",
        ],
        warning: "大涨当天拖到3点后卖，第二天回调，到手利润大幅缩水",
      },
    ],
  },
  {
    id: "etf_trading", title: "三、场内 ETF/LOF", icon: "📈",
    rules: [
      {
        title: "交易时段",
        items: ["上午 9:30–11:30，下午 13:00–15:00", "14:57–15:00 尾盘集合竞价，不可撤单"],
      },
      {
        title: "T+0 / T+1 规则",
        items: [
          "T+1（A股宽基/行业ETF）：当日买入，次交易日才能卖出",
          "T+0（跨境/黄金/债券ETF）：当日买卖不限次数",
        ],
      },
    ],
  },
];
