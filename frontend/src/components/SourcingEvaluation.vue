<template>
  <div v-if="evaluation" class="evaluation">
    <el-alert v-if="evaluation.stale" title="此评估已过期：商品核心资料已改变，请重新分析后审核。" type="warning" :closable="false" />
    <div class="scores">
      <el-statistic title="图片视觉评分（0–100）" :value="Number(evaluation.visual_score)" />
      <el-statistic title="资料完整度规则评分（0–100）" :value="evaluation.rule_score" />
      <div><strong>市场数据指标：未接入</strong><p>无真实销量、热度或利润率数据</p></div>
    </div>
    <p><b>商品类型：</b>{{ evaluation.vision.product_type }}</p>
    <p><b>展示质量：</b>{{ evaluation.vision.presentation_quality }}</p>
    <p><b>视觉卖点：</b>{{ evaluation.vision.visual_selling_points.join('；') || '未发现明确卖点' }}</p>
    <p><b>视觉评分依据：</b>{{ evaluation.vision.score_basis.join('；') }}</p>
    <el-tag v-for="r in evaluation.rule_basis" :key="r.check" :type="r.passed ? 'success' : 'info'" class="tag">{{ r.check }}：{{ r.passed ? '是' : '否' }}</el-tag>
    <h4>潜在风险</h4>
    <p v-for="(risk, i) in evaluation.vision.potential_risks" :key="i"><el-tag type="warning">{{ riskLabels[risk.kind] || risk.kind }}</el-tag> {{ risk.detail }}</p>
    <p v-if="!evaluation.vision.potential_risks.length">未指出风险不代表商品无风险，需人工核实。</p>
    <template v-if="evaluation.text_analysis">
      <h4>DeepSeek 文本建议</h4>
      <p><b>建议英文名称：</b>{{ evaluation.text_analysis.english_title_suggestion }}</p>
      <p><b>建议进入人工审核：</b>{{ evaluation.text_analysis.worth_review ? '是' : '否' }}（仅模型建议）</p>
      <p><b>推荐理由：</b>{{ evaluation.text_analysis.recommendation_reasons.join('；') }}</p>
      <p><b>优势：</b>{{ evaluation.text_analysis.advantages.join('；') }}</p>
      <p><b>不足：</b>{{ evaluation.text_analysis.disadvantages.join('；') }}</p>
      <p><b>差异化方向：</b>{{ evaluation.text_analysis.differentiation.join('；') }}</p>
      <p><b>采购成本风险：</b>{{ evaluation.text_analysis.cost_risks.join('；') }}</p>
      <div v-for="(fit, i) in evaluation.text_analysis.market_fit_suggestions" :key="i">
        <p><b>{{ fit.target_market }} 市场适配建议：</b>{{ fit.suggestion }}</p>
        <p>依据：{{ fit.basis }}；局限：{{ fit.limitation }}</p>
      </div>
      <p class="muted">文本分析局限：{{ evaluation.text_analysis.limitations.join('；') }}</p>
    </template>
    <el-alert v-else title="DeepSeek 未配置，此评估只有真实视觉结果；未生成文本建议。" type="info" :closable="false" />
    <p class="muted">视觉分析局限：{{ evaluation.vision.limitations.join('；') }}</p>
    <el-collapse><el-collapse-item title="调用证据 / 输入版本 / 规则定义"><pre>{{ JSON.stringify(evaluation.evidence, null, 2) }}</pre></el-collapse-item></el-collapse>
  </div>
  <el-empty v-else description="尚无成功的 AI 评估" />
</template>
<script setup lang="ts">
import type { Evaluation } from '@/api/sourcing'
defineProps<{ evaluation: Evaluation | null }>()
const riskLabels: Record<string, string> = { observed: '图片观察', inferred: '模型推断', needs_verification: '待人工核实' }
</script>
<style scoped>
.scores { display: flex; flex-wrap: wrap; gap: 32px; margin: 20px 0; }
.tag { margin: 4px; }.muted { color: #73767a; }p { line-height: 1.7; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
