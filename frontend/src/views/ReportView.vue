<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NButton, NSpin, NAlert, NTabs, NTabPane, NDescriptions, NDescriptionsItem, NGrid, NGi, NTag, NSpace, NText } from 'naive-ui'
import { useAppStore } from '../stores/app'
import { useReportStore } from '../stores/report'
import { fmtPct, priceColor } from '../utils/format'
import MetricCard from '../components/MetricCard.vue'

const app = useAppStore()
const rpt = useReportStore()

async function generate() {
  await rpt.generate(app.currentStockCode)
}

const r = computed(() => rpt.currentReport)
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
          <div style="display: flex; align-items: center; gap: 16px">
            <NTag :type="r.overall_rating === '強力買進' || r.overall_rating === '買進' ? 'error' : r.overall_rating === '賣出' ? 'success' : 'warning'" size="large">
              {{ r.overall_rating }}
            </NTag>
            <span style="font-size: 24px; font-weight: 700">{{ r.current_price?.toFixed(2) }}</span>
            <NText depth="3">{{ r.stock_name }} | {{ r.report_date?.slice(0, 10) }}</NText>
          </div>
        </NCard>

        <!-- 摘要 -->
        <NCard title="投資摘要" size="small" style="margin-bottom: 16px">
          <p style="white-space: pre-wrap; line-height: 1.6">{{ r.summary_text }}</p>
        </NCard>

        <NTabs type="line">
          <!-- 價格表現 -->
          <NTabPane name="perf" tab="價格表現">
            <NGrid :cols="5" :x-gap="12" :y-gap="12">
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
            <NDescriptions :column="2" label-placement="left" size="small">
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
            </NDescriptions>
          </NTabPane>

          <!-- 目標價 -->
          <NTabPane name="targets" tab="目標價">
            <table style="width: 100%; font-size: 13px; border-collapse: collapse">
              <thead>
                <tr style="border-bottom: 2px solid #e2e8f0">
                  <th style="text-align: left; padding: 6px">時間</th>
                  <th style="text-align: left; padding: 6px">情境</th>
                  <th style="text-align: right; padding: 6px">目標價</th>
                  <th style="text-align: right; padding: 6px">上檔%</th>
                  <th style="text-align: left; padding: 6px">依據</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(t, i) in r.price_targets" :key="i" style="border-bottom: 1px solid #f0f0f0">
                  <td style="padding: 6px">{{ t.timeframe }}</td>
                  <td style="padding: 6px">{{ t.scenario }}</td>
                  <td style="padding: 6px; text-align: right; font-weight: 600">{{ t.target_price?.toFixed(2) }}</td>
                  <td style="padding: 6px; text-align: right" :style="{ color: priceColor(t.upside_pct) }">{{ fmtPct(t.upside_pct) }}</td>
                  <td style="padding: 6px; font-size: 12px; color: #718096">{{ t.rationale }}</td>
                </tr>
              </tbody>
            </table>
          </NTabPane>

          <!-- 基本面 -->
          <NTabPane name="fund" tab="基本面">
            <NDescriptions :column="2" label-placement="left" size="small">
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
              <span style="color: #a0aec0; margin-left: 8px">{{ n.source }} | {{ n.date }}</span>
            </div>
          </NTabPane>

          <!-- 行動建議 -->
          <NTabPane name="action" tab="行動建議">
            <div v-if="r.actionable_recommendation" style="line-height: 1.8">
              <p><strong>動作:</strong> {{ r.actionable_recommendation.action }}</p>
              <p v-if="r.actionable_recommendation.entry_zone"><strong>進場區間:</strong> {{ r.actionable_recommendation.entry_zone }}</p>
              <p v-if="r.actionable_recommendation.stop_loss"><strong>停損:</strong> {{ r.actionable_recommendation.stop_loss }}</p>
              <p v-if="r.actionable_recommendation.take_profit"><strong>停利:</strong> {{ r.actionable_recommendation.take_profit }}</p>
              <p v-if="r.actionable_recommendation.position_size"><strong>部位建議:</strong> {{ r.actionable_recommendation.position_size }}</p>
              <p v-if="r.actionable_recommendation.rationale"><strong>理由:</strong> {{ r.actionable_recommendation.rationale }}</p>
            </div>
          </NTabPane>

          <!-- 風險 -->
          <NTabPane name="risk" tab="風險">
            <NDescriptions :column="2" label-placement="left" size="small">
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
