<script setup lang="ts">
import { h, computed } from 'vue'
import { NCard, NButton, NSpin, NAlert, NTabs, NTabPane, NDescriptions, NDescriptionsItem, NGrid, NGi, NTag, NSpace, NText, NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useReportStore } from '../stores/report'
import { fmtPct, priceColor } from '../utils/format'
import { useResponsive } from '../composables/useResponsive'
import MetricCard from '../components/MetricCard.vue'

const app = useAppStore()
const rpt = useReportStore()

async function generate() {
  await rpt.generate(app.currentStockCode)
}

const r = computed(() => rpt.currentReport)

const { cols } = useResponsive()
const perfCols = cols(3, 5, 5)
const descCols = cols(1, 2, 2)
const instCols = cols(2, 4, 4)

const priceTargetColumns: DataTableColumns = [
  { title: '時間', key: 'timeframe', width: 70 },
  { title: '情境', key: 'scenario', width: 70 },
  { title: '目標價', key: 'target_price', width: 90,
    render: (row: any) => h('span', { style: { fontWeight: 600 } }, row.target_price?.toFixed(2)) },
  { title: '上檔%', key: 'upside_pct', width: 80,
    render: (row: any) => h('span', { style: { color: priceColor(row.upside_pct) } }, fmtPct(row.upside_pct)) },
  { title: '依據', key: 'rationale', ellipsis: { tooltip: true } },
]
</script>

<template>
  <div>
    <h2 style="margin: 0 0 16px">{{ app.currentStockCode }} {{ app.currentStockName }} - 分析報告</h2>

    <NSpace style="margin-bottom: 16px">
      <NButton type="primary" @click="generate" :loading="rpt.isGenerating">產生報告</NButton>
    </NSpace>

    <NSpin :show="rpt.isGenerating">
      <NAlert v-if="rpt.error" type="error" style="margin-bottom: 16px">{{ rpt.error }}</NAlert>

      <template v-if="r">
        <!-- 評等橫幅 -->
        <NCard size="small" style="margin-bottom: 16px">
          <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap">
            <NTag :type="r.overall_rating === '強力買進' || r.overall_rating === '買進' ? 'error' : r.overall_rating === '賣出' || r.overall_rating === '強力賣出' ? 'success' : 'warning'" size="large">
              {{ r.overall_rating }}
            </NTag>
            <span style="font-size: 24px; font-weight: 700">{{ r.current_price?.toFixed(2) }}</span>
            <NText depth="3">{{ r.stock_name }} | {{ r.report_date?.slice(0, 10) }}</NText>
            <NTag v-if="r.is_biotech" type="info" size="small" round>Biotech Mode</NTag>
            <NTag v-if="r.institutional_score" :type="(r.institutional_score?.score || 0) > 1 ? 'error' : (r.institutional_score?.score || 0) < -1 ? 'success' : 'default'" size="small">
              籌碼: {{ (r.institutional_score?.score || 0) > 0 ? '+' : '' }}{{ r.institutional_score?.score?.toFixed(1) }}
            </NTag>
          </div>
        </NCard>

        <!-- 摘要 -->
        <NCard title="投資摘要" size="small" style="margin-bottom: 16px">
          <p style="white-space: pre-wrap; line-height: 1.6">{{ r.summary_text }}</p>
        </NCard>

        <NTabs type="line">
          <!-- 價格表現 -->
          <NTabPane name="perf" tab="價格表現">
            <NGrid :cols="perfCols" :x-gap="12" :y-gap="12">
              <NGi><MetricCard title="1週" :value="fmtPct(r.price_change_1w)" :color="priceColor(r.price_change_1w)" /></NGi>
              <NGi><MetricCard title="1月" :value="fmtPct(r.price_change_1m)" :color="priceColor(r.price_change_1m)" /></NGi>
              <NGi><MetricCard title="3月" :value="fmtPct(r.price_change_3m)" :color="priceColor(r.price_change_3m)" /></NGi>
              <NGi><MetricCard title="6月" :value="fmtPct(r.price_change_6m)" :color="priceColor(r.price_change_6m)" /></NGi>
              <NGi><MetricCard title="1年" :value="fmtPct(r.price_change_1y)" :color="priceColor(r.price_change_1y)" /></NGi>
            </NGrid>
            <div style="margin-top: 12px; font-size: 13px">
              52週高: {{ r.high_52w?.toFixed(2) }} ({{ fmtPct(r.pct_from_52w_high) }}) |
              52週低: {{ r.low_52w?.toFixed(2) }} ({{ fmtPct(r.pct_from_52w_low) }})
            </div>
          </NTabPane>

          <!-- 技術面 -->
          <NTabPane name="tech" tab="技術面">
            <NDescriptions :column="descCols" label-placement="left" size="small">
              <NDescriptionsItem label="趨勢方向">{{ r.trend_direction }}</NDescriptionsItem>
              <NDescriptionsItem label="趨勢強度">{{ r.trend_strength }}</NDescriptionsItem>
              <NDescriptionsItem label="動能狀態">{{ r.momentum_status }}</NDescriptionsItem>
              <NDescriptionsItem label="波動度">{{ r.volatility_level }}</NDescriptionsItem>
              <NDescriptionsItem label="ADX">{{ r.adx_value?.toFixed(1) }} - {{ r.adx_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem label="RSI">{{ r.rsi_value?.toFixed(1) }} - {{ r.rsi_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem label="MACD">{{ r.macd_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem label="KD">{{ r.kd_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem label="量能">{{ r.volume_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem label="波動">{{ r.volatility_interpretation }}</NDescriptionsItem>
              <NDescriptionsItem v-if="r.technical_bias" label="綜合偏向">{{ r.technical_bias }}</NDescriptionsItem>
            </NDescriptions>
            <div v-if="r.technical_conflicts?.length" style="margin-top: 12px">
              <NText depth="2" style="font-size: 13px; font-weight: 600">技術面矛盾:</NText>
              <ul style="margin: 4px 0; padding-left: 20px">
                <li v-for="(c, i) in r.technical_conflicts" :key="i" style="margin-bottom: 4px; font-size: 13px; color: #e65100">{{ c }}</li>
              </ul>
            </div>
          </NTabPane>

          <!-- 目標價 -->
          <NTabPane name="targets" tab="目標價">
            <NDataTable
              :columns="priceTargetColumns"
              :data="r.price_targets || []"
              size="small"
              :scroll-x="480"
            />
          </NTabPane>

          <!-- 基本面 -->
          <NTabPane name="fund" tab="基本面">
            <NDescriptions :column="descCols" label-placement="left" size="small">
              <NDescriptionsItem v-for="(val, key) in r.fundamentals" :key="key" :label="String(key)">
                {{ val != null ? (typeof val === 'number' ? val.toFixed(2) : val) : '-' }}
              </NDescriptionsItem>
            </NDescriptions>
            <div v-if="r.fundamental_interpretation" style="margin-top: 12px; font-size: 13px; line-height: 1.6">
              {{ r.fundamental_interpretation }}
            </div>
          </NTabPane>

          <!-- 消息面 -->
          <NTabPane name="news" tab="消息面">
            <NTag :type="r.news_sentiment_label === '正面' ? 'success' : r.news_sentiment_label === '負面' ? 'error' : 'default'" style="margin-bottom: 12px">
              {{ r.news_sentiment_label }} ({{ r.news_sentiment_score?.toFixed(2) }})
            </NTag>
            <div v-for="(n, i) in r.news_items?.slice(0, 10)" :key="i" style="margin-bottom: 8px; font-size: 13px">
              <a :href="n.url" target="_blank" style="color: #2196f3">{{ n.title }}</a>
              <span style="color: var(--text-dimmed); margin-left: 8px">{{ n.source }} | {{ n.date }}</span>
            </div>
          </NTabPane>

          <!-- 籌碼面 (Gemini R19) -->
          <NTabPane name="inst" tab="籌碼面">
            <template v-if="r.institutional_score">
              <NGrid :cols="instCols" :x-gap="12" :y-gap="12" style="margin-bottom: 16px">
                <NGi>
                  <MetricCard title="籌碼評分"
                    :value="((r.institutional_score.score || 0) > 0 ? '+' : '') + (r.institutional_score.score?.toFixed(1) || '0')"
                    :color="priceColor(r.institutional_score.score || 0)" subtitle="範圍 -5 ~ +5" />
                </NGi>
                <NGi>
                  <MetricCard title="連續天數"
                    :value="String(Math.abs(r.institutional_score.consecutive_days || 0)) + '日' + ((r.institutional_score.consecutive_days || 0) > 0 ? '買超' : (r.institutional_score.consecutive_days || 0) < 0 ? '賣超' : '')"
                    :color="priceColor(r.institutional_score.consecutive_days || 0)" />
                </NGi>
                <NGi>
                  <MetricCard title="主力方向" :value="r.institutional_score.dominant_force || '-'" />
                </NGi>
                <NGi v-if="r.is_biotech">
                  <MetricCard title="分析模式" value="生技專用" subtitle="P/E, ROE 降權" color="#2196f3" />
                </NGi>
              </NGrid>
              <NDescriptions :column="1" label-placement="left" size="small">
                <NDescriptionsItem label="籌碼分析">{{ r.institutional_score.details }}</NDescriptionsItem>
              </NDescriptions>
              <div v-if="r.rating_weights" style="margin-top: 12px; font-size: 13px; color: var(--text-dimmed)">
                權重配置：技術面 {{ (r.rating_weights.tech * 100).toFixed(0) }}% |
                基本面 {{ (r.rating_weights.fund * 100).toFixed(0) }}% |
                籌碼面 {{ (r.rating_weights.inst * 100).toFixed(0) }}% |
                產業面 {{ (r.rating_weights.sector * 100).toFixed(0) }}%
              </div>
            </template>
            <NText v-else depth="3">無法人買賣超資料</NText>
          </NTabPane>

          <!-- 行動建議 -->
          <NTabPane name="action" tab="行動建議">
            <div v-if="r.actionable_recommendation" style="line-height: 1.8">
              <p><strong>動作:</strong>
                <NTag :type="r.actionable_recommendation.action === 'BUY' ? 'error' : r.actionable_recommendation.action === 'SELL' || r.actionable_recommendation.action === 'AVOID' ? 'success' : 'warning'" size="small">
                  {{ r.actionable_recommendation.action }}
                </NTag>
              </p>
              <p><strong>投資論點:</strong> {{ r.actionable_recommendation.thesis }}</p>
              <p v-if="r.actionable_recommendation.entry_low != null">
                <strong>進場區間:</strong> ${{ r.actionable_recommendation.entry_low?.toFixed(2) }} ~ ${{ r.actionable_recommendation.entry_high?.toFixed(2) }}
                <span v-if="r.actionable_recommendation.entry_basis" style="color: var(--text-dimmed); font-size: 12px"> ({{ r.actionable_recommendation.entry_basis }})</span>
              </p>
              <p v-if="r.actionable_recommendation.stop_loss != null">
                <strong>停損:</strong> ${{ r.actionable_recommendation.stop_loss?.toFixed(2) }} ({{ fmtPct(r.actionable_recommendation.stop_loss_pct) }})
                <span v-if="r.actionable_recommendation.stop_loss_basis" style="color: var(--text-dimmed); font-size: 12px"> ({{ r.actionable_recommendation.stop_loss_basis }})</span>
              </p>
              <p v-if="r.actionable_recommendation.take_profit_t1 != null">
                <strong>目標:</strong> T1=${{ r.actionable_recommendation.take_profit_t1?.toFixed(2) }}
                <template v-if="r.actionable_recommendation.take_profit_t2"> / T2=${{ r.actionable_recommendation.take_profit_t2?.toFixed(2) }}</template>
              </p>
              <p v-if="r.actionable_recommendation.position_pct"><strong>部位建議:</strong> {{ r.actionable_recommendation.position_pct }}
                <span v-if="r.actionable_recommendation.position_basis" style="color: var(--text-dimmed); font-size: 12px"> ({{ r.actionable_recommendation.position_basis }})</span>
              </p>
              <div v-if="r.actionable_recommendation.trigger_conditions?.length" style="margin-top: 12px">
                <strong>觸發條件:</strong>
                <ul style="margin: 4px 0; padding-left: 20px">
                  <li v-for="(t, i) in r.actionable_recommendation.trigger_conditions" :key="i" style="margin-bottom: 4px; font-size: 13px">{{ t }}</li>
                </ul>
              </div>
            </div>
          </NTabPane>

          <!-- 風險 -->
          <NTabPane name="risk" tab="風險">
            <NDescriptions :column="descCols" label-placement="left" size="small">
              <NDescriptionsItem label="風險等級">{{ r.key_risk_level }}</NDescriptionsItem>
              <NDescriptionsItem label="風報比">{{ r.risk_reward_ratio?.toFixed(2) }}</NDescriptionsItem>
              <NDescriptionsItem label="1年最大回撤">{{ fmtPct(r.max_drawdown_1y) }}</NDescriptionsItem>
              <NDescriptionsItem label="當前回撤">{{ fmtPct(r.current_drawdown) }}</NDescriptionsItem>
            </NDescriptions>
            <div v-if="r.risk_interpretation" style="margin-top: 12px; font-size: 13px">{{ r.risk_interpretation }}</div>
          </NTabPane>
        </NTabs>
      </template>
    </NSpin>
  </div>
</template>
