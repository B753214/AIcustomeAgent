import type { StageKey } from './types'

export const API_KEY_STORAGE = 'dashboard_api_key'

export const SUGS = [
  { label: '七天无理由退货怎么操作？', text: '七天无理由退货怎么操作？' },
  { label: '查询订单 202608090001 的物流', text: '查询订单 202608090001 的物流' },
  { label: '你好，简单介绍下你们平台', text: '你好，简单介绍下你们平台' },
  { label: '运费谁承担？', text: '运费谁承担？' },
  {
    label: '告警排查（字段+监控链接）',
    text:
      'P1 【指标】：填单BFF失败\n【配置ID】：11664\nhttps://info-plate.fc.alibaba-inc.com/monitor/searchall?marketConfigId=11664',
  },
] as const

export const STAGES: { key: StageKey; icon: string; name: string }[] = [
  { key: 'rate_limit', icon: '🛡️', name: '限流检查' },
  { key: 'cache', icon: '💾', name: '语义缓存' },
  { key: 'crew', icon: '🤖', name: 'Crew Agent' },
  { key: 'alarm_fetch', icon: '📡', name: '告警拉数' },
  { key: 'alarm', icon: '🚨', name: '告警排查' },
  { key: 'intent', icon: '🎯', name: '意图识别' },
  { key: 'retrieve', icon: '🔍', name: '知识检索' },
  { key: 'generate', icon: '✨', name: '生成回答' },
  { key: 'save', icon: '💾', name: '记忆写入' },
  { key: 'error', icon: '⚠️', name: '异常' },
]

export const STAGE_MAP: Record<string, StageKey> = {
  rate_limit: 'rate_limit',
  cache: 'cache',
  crew: 'crew',
  alarm_fetch: 'alarm_fetch',
  alarm: 'alarm',
  intent: 'intent',
  retrieval: 'retrieve',
  retrieve: 'retrieve',
  tool: 'generate',
  generate: 'generate',
  write: 'save',
  error: 'error',
}

export const INTENT_LABEL: Record<string, string> = {
  knowledge: '知识问答',
  order: '订单查询',
  chat: '闲聊',
  crew: 'Crew',
  alarm: '告警排查',
}
