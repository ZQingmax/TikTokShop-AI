<template>
  <div class="workbench">
    <el-alert type="info" :closable="false" title="货源资料 → 编辑商品草稿 → 人工采纳 AI 结果 → 检查并确认 → 妙手店铺采集箱" />
    <div class="model-bar" v-if="config">
      <el-tag :type="config.configured ? 'success' : 'warning'">百炼 {{ config.configured ? '已配置' : '未配置' }}</el-tag>
      <span>识别：{{ config.ocr_model }} · 文案：{{ config.copy_model }} · 填充：{{ config.fill_model }}</span><span>图片：{{ config.image_model }} · {{ config.resolution }}</span>
      <span>翻译：{{ config.translation_model }}</span>
      <el-tag :type="config.miaoshou_configured ? 'success' : 'warning'">妙手图片空间 {{ config.miaoshou_configured ? '已配置' : '未配置' }}</el-tag>
    </div>
    <div class="workspace">
      <aside>
        <div class="filters">
          <el-input v-model="keyword" placeholder="搜索草稿标题" clearable @keyup.enter="search" @clear="search" />
          <el-select v-model="filterState" placeholder="全部状态" clearable @change="search">
            <el-option v-for="(label, key) in draftStates" :key="key" :label="label" :value="key" />
          </el-select>
          <el-button @click="loadList">刷新列表</el-button>
        </div>
        <el-empty v-if="!rows.length" description="从我的采集箱选择商品进入工作台" :image-size="65" />
        <button v-for="row in rows" :key="row.id" class="draft-row" :class="{ selected: current?.id === row.id }" @click="open(row.id)">
          <img v-if="row.content.imgUrls[0]" :src="row.content.imgUrls[0]" referrerpolicy="no-referrer" alt="商品预览" />
          <span><strong>{{ row.content.title || '待编辑商品' }}</strong><small>{{ row.shop_id ? shopName(row.shop_id) : '未选择店铺' }}</small><small>{{ draftStates[row.state] }}</small></span>
        </button>
        <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="loadList" small />
      </aside>
      <main v-if="current" v-loading="busy" @keydown="onEditorKeydown">
        <div class="editor-toolbar">
          <div><strong>{{ current.content.title || '商品草稿' }}</strong><p class="muted">{{ current.market }} · {{ current.currency }} · 最近保存 {{ formatTime(current.updated_at) }} <span v-if="dirty">· 有未保存修改</span></p></div>
          <el-tag>{{ draftStates[current.state] }}</el-tag>
          <el-button @click="save">保存草稿</el-button><el-button @click="check">检查草稿</el-button>
          <el-button type="primary" :disabled="!current.shop_id || syncActive || upToDate" :title="current.shop_id ? '' : '先选择目标店铺'" @click="sync()">{{ syncLabel }}</el-button>
          <el-button type="danger" plain :disabled="syncActive" @click="deleteDraft">删除草稿</el-button>
        </div>
        <el-alert v-if="current.synced_version && current.synced_version !== current.version" type="warning" :closable="false" title="已同步到妙手；之后的修改尚未同步" />
        <el-form label-position="top" class="binding">
          <el-form-item label="目标店铺" :title="shopLocked ? '已同步到此店铺或同步进行中，不能更换' : ''"><el-select v-model="current.shop_id" :disabled="shopLocked" placeholder="请选择目标店铺" clearable filterable>
            <el-option v-for="shop in shops" :key="shop.shopId" :value="shop.shopId" :label="shop.platformShopName || shop.shopNick || `店铺 ${shop.shopId}`" />
          </el-select></el-form-item>
          <el-form-item label="目标语言"><el-select v-model="current.language"><el-option v-for="(label, code) in languages" :key="code" :value="code" :label="label" /></el-select></el-form-item>
        </el-form>
        <div class="inline fill-bar">
          <el-button :disabled="!config?.configured || fillActive" :loading="fillActive" @click="ai('fill')">AI 填充建议</el-button>
          <el-button :disabled="!fillableKeys.length" @click="applyAllHints">采纳全部建议（{{ fillableKeys.length }} 项空白）</el-button>
          <span class="muted">灰色提示为建议值：在空白字段按 Tab 填入，或直接输入覆盖。建议来自货源资料或 AI 估算，提交前请核实。</span>
        </div>
        <el-tabs v-model="section">
          <el-tab-pane label="基本信息" name="copy">
            <div class="two-column">
              <el-card shadow="never"><template #header>原始货源资料</template>
                <h3>{{ current.source_snapshot.name }}</h3><p class="source-description">{{ current.source_snapshot.description || '来源未提供描述' }}</p>
                <p>采购价：{{ current.source_snapshot.purchase_price ?? '未知' }} {{ current.source_snapshot.currency }}</p>
                <p>货源库存：{{ current.source_snapshot.source_stock ?? '未知' }}</p>
                <p>供应商：{{ current.source_snapshot.supplier || '待核实' }}</p>
                <h4>货源链接</h4>
                <div v-for="link in sourceLinks" :key="link.url" class="inline source-link"><span v-if="link.remark" class="muted">{{ link.remark }}</span>
                  <el-link :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.url }}</el-link><el-button link type="primary" @click="copyText(link.url)">复制</el-button></div>
                <el-collapse><el-collapse-item title="原始 SKU 与资料快照"><pre>{{ JSON.stringify(current.source_snapshot, null, 2) }}</pre></el-collapse-item></el-collapse>
              </el-card>
              <el-form label-position="top">
                <el-form-item :label="`商品标题（${current.content.title.length}/255）`"><el-input v-model="current.content.title" maxlength="500" /></el-form-item>
                <el-form-item label="商品卖点"><div class="full"><div v-for="(_bullet, i) in current.content.bullet_points" :key="i" class="inline">
                  <el-input v-model="current.content.bullet_points[i]" /><el-button @click="current.content.bullet_points.splice(i, 1)">移除</el-button>
                </div><el-button :disabled="current.content.bullet_points.length >= 10" @click="current.content.bullet_points.push('')">添加卖点</el-button></div></el-form-item>
                <el-form-item label="详细描述 · 文字"><el-input v-model="current.content.notes" type="textarea" :rows="8" maxlength="20000" /></el-form-item>
                <el-form-item :label="`详细描述 · 图片（${current.content.descImgUrls.length}/50，按顺序展示在文字之后）`"><div class="full">
                  <el-button v-if="!current.content.descImgUrls.length && sourceDescImages.length" type="primary" plain @click="importDescImages">从货源导入详情图（{{ sourceDescImages.length }} 张）</el-button>
                  <div class="desc-grid"><div v-for="(url, i) in current.content.descImgUrls" :key="url" class="desc-card">
                    <el-image :src="url" fit="contain" :preview-src-list="current.content.descImgUrls" :initial-index="i" preview-teleported referrerpolicy="no-referrer" />
                    <div class="inline"><el-button size="small" link :disabled="i === 0" @click="moveDescImage(i, -1)">上移</el-button>
                      <el-button size="small" link :disabled="i === current.content.descImgUrls.length - 1" @click="moveDescImage(i, 1)">下移</el-button>
                      <el-button size="small" link type="primary" :disabled="!imageEnabled" @click="translateImage(url)">翻译</el-button>
                      <el-button size="small" link type="danger" @click="removeDescImage(url)">移除</el-button></div>
                  </div></div>
                  <div class="inline"><el-input v-model="newDescImageUrl" placeholder="添加详情图片 URL" /><el-button :disabled="current.content.descImgUrls.length >= 50" @click="addDescImage">添加详情图</el-button></div>
                </div></el-form-item>
                <el-form-item label="人工确认的商品事实（供 AI 使用）"><el-input v-model="current.content.confirmed_facts" type="textarea" :rows="3" placeholder="仅填写已核实的材质、用途等信息" /></el-form-item>
                <el-button type="primary" :disabled="!config?.configured" @click="ai('copy')">生成 {{ current.language }} 文案</el-button>
                <el-collapse v-if="current.content.recognized_text.length"><el-collapse-item title="已采纳的图片识别文字"><pre>{{ JSON.stringify(current.content.recognized_text, null, 2) }}</pre></el-collapse-item></el-collapse>
              </el-form>
            </div>
          </el-tab-pane>
          <el-tab-pane label="产品属性" name="attributes">
            <el-alert v-if="!boundShop" type="info" :closable="false" title="先选择并保存店铺，再加载真实类目、类目属性和仓库。" />
            <div class="inline"><el-button :disabled="!boundShop" @click="loadOptions">刷新类目 / 仓库</el-button>
              <div data-hint="cid"><el-select v-model="current.content.cid" :placeholder="hintPlaceholder('cid', '选择末级类目')" filterable style="width:400px" @change="categoryChanged"><el-option v-for="category in leafCategories" :key="category.cid" :value="String(category.cid)" :label="category.path" :disabled="category.disabled" /></el-select></div>
              <template v-if="showHint('cid')"><el-button link type="primary" :disabled="!boundShop" @click="applyHint('cid')">采纳建议类目</el-button><small class="muted">{{ hints.cid.source }}</small></template>
            </div>
            <h4>TikTok 类目属性（同步到妙手）</h4>
            <p v-if="!productRules.length" class="muted">选择末级类目后显示该类目的属性。</p>
            <el-form label-position="top" class="attribute-grid"><el-form-item v-for="rule in productRules" :key="rule.attrId" :label="`${rule.name}${rule.isMandatory ? ' *' : ''}`" :data-hint="`attr:${rule.attrId}`" :title="hints[`attr:${rule.attrId}`]?.source">
              <el-select :model-value="attributeValues(rule.attrId)" multiple filterable :allow-create="!!rule.isCustomized" default-first-option :placeholder="hintPlaceholder(`attr:${rule.attrId}`, '请选择')" @change="(values: string[]) => setAttribute(rule, values)">
                <el-option v-for="value in rule.values || []" :key="value.id" :value="String(value.id)" :label="value.name" />
              </el-select></el-form-item></el-form>
            <h4>货源属性（参考资料，供人工核对与 AI 填写，不直接同步）</h4>
            <el-button v-if="!current.content.sourceAttributes.length && suggestions?.source.attributes.length" type="primary" plain @click="importSourceAttributes">从货源导入属性（{{ suggestions.source.attributes.length }} 项）</el-button>
            <div class="source-attrs"><div v-for="(attr, i) in current.content.sourceAttributes" :key="i" class="source-attr">
              <el-input v-model="attr.name" placeholder="属性名" maxlength="100" /><el-input v-model="attr.value" placeholder="属性值" maxlength="500" />
              <el-button link type="danger" @click="current.content.sourceAttributes.splice(i, 1)">删除</el-button>
            </div></div>
            <el-button link type="primary" :disabled="current.content.sourceAttributes.length >= 100" @click="current.content.sourceAttributes.push({ name: '', value: '' })">+ 新增属性</el-button>
          </el-tab-pane>
          <el-tab-pane label="销售属性 / SKU" name="skus">
            <el-alert v-if="!boundShop" type="info" :closable="false" title="先选择并保存店铺，再加载销售属性和仓库。" />
            <h4>销售规格（按当前类目映射；调整后请重新生成 SKU）</h4>
            <el-alert v-if="unmappedSpecs.length && !saleRules.length" type="info" :closable="false" class="spec-hint"
              title="货源规格需要对应到 TikTok 类目的销售属性：请先在「产品属性」中选择末级类目（需先选择店铺）。" />
            <el-alert v-else-if="unmappedSpecs.length" type="warning" :closable="false" class="spec-hint"
              title="以下规格来自货源，还没有对应到当前类目的销售属性。TikTok 只接受类目内的销售属性，未对应前同步会跳过规格与 SKU。选择对应属性即可，规格值、图片和 SKU 资料都会保留：">
              <div v-for="{ prop, index } in unmappedSpecs" :key="index" class="inline spec-map">
                <strong>「{{ prop.attrName }}」</strong><span class="muted">{{ prop.attrValueList.map((v: any) => v.attrValue).join('、') }}</span><span>对应到</span>
                <el-select placeholder="选择类目销售属性" size="small" style="width:220px" @change="(attrId: string) => mapSpec(index, attrId)">
                  <el-option v-for="rule in saleRules" :key="rule.attrId" :value="String(rule.attrId)" :label="`${rule.name}${rule.isCustomized ? '（可自定义值）' : '（仅预设值）'}`" />
                </el-select>
              </div>
            </el-alert>
            <el-alert v-if="specSuggestion.length" type="success" :closable="false" class="spec-hint">
              <template #title>AI 建议的规格映射：<span v-for="spec in specSuggestion" :key="spec.attr_id">「{{ spec.source_property }}」→ {{ spec.name }}（{{ spec.values.length }} 个值）</span>
                <el-button size="small" type="primary" @click="applySpecSuggestion">采纳规格并生成 SKU</el-button></template>
            </el-alert>
            <el-form label-position="top" class="attribute-grid"><el-form-item v-for="rule in saleRules" :key="rule.attrId" :label="`${rule.name}${rule.isMandatory ? ' *' : ''}`">
              <el-select :model-value="saleValues(rule.attrId)" multiple filterable :allow-create="!!rule.isCustomized" default-first-option @change="(values: string[]) => setSaleAttribute(rule, values)">
                <el-option v-for="value in rule.values || []" :key="value.id" :value="String(value.id)" :label="value.name" />
              </el-select></el-form-item></el-form>
            <el-button @click="rebuildSkus">按销售规格生成 SKU 组合</el-button>
            <div class="inline pricing"><span>定价建议：1 {{ suggestions?.source.currency || 'CNY' }} =</span>
              <el-input-number v-model="pricing.rate" :min="0" :precision="4" :controls="false" placeholder="汇率" /><span>{{ current.currency }} × 倍率</span>
              <el-input-number v-model="pricing.markup" :min="0" :precision="2" :controls="false" placeholder="如 2.5" />
              <span class="muted">按货源价格计算售价建议；仅保存在本浏览器</span></div>
            <h4>SKU 列表（{{ skuRows.length }} 个）</h4>
            <el-table :data="skuRows" row-key="key" class="sku-table">
              <el-table-column label="规格" min-width="170"><template #default="{ row }">{{ skuLabel(row.key) }}<small class="muted">{{ row.key }}</small></template></el-table-column>
              <el-table-column min-width="140"><template #header>货源价格 (CNY) <el-button link type="primary" @click="batchSet('originPrice', '货源价格')">批量</el-button></template>
                <template #default="{ row }"><div :data-hint="`sku:${row.key}:originPrice`" :title="hints[`sku:${row.key}:originPrice`]?.source"><el-input-number v-model="row.sku.originPrice" :min="0" :controls="false" :placeholder="hintPlaceholder(`sku:${row.key}:originPrice`)" /></div></template></el-table-column>
              <el-table-column min-width="150"><template #header>售价 ({{ current.currency }}) <el-button link type="primary" @click="batchSet('price', '售价')">批量</el-button></template>
                <template #default="{ row }"><div :data-hint="`sku:${row.key}:price`" :title="hints[`sku:${row.key}:price`]?.source"><el-input-number v-model="row.sku.price" :min="0" :controls="false" :placeholder="hintPlaceholder(`sku:${row.key}:price`)" /></div></template></el-table-column>
              <el-table-column min-width="240"><template #header>仓库库存 <el-button link type="primary" :disabled="!warehouseOptions.length" @click="batchSet('stock', '库存（第一个仓库）')">批量</el-button></template>
                <template #default="{ row }"><div v-for="(warehouse, wi) in warehouseOptions" :key="warehouse.warehouseId" class="warehouse-row" :data-hint="wi === 0 ? `sku:${row.key}:stock` : undefined" :title="wi === 0 ? hints[`sku:${row.key}:stock`]?.source : undefined"><span>{{ warehouse.warehouseName }}</span><el-input-number :model-value="warehouseStock(row.sku, warehouse.warehouseId)" :min="0" :precision="0" :controls="false" :placeholder="wi === 0 ? hintPlaceholder(`sku:${row.key}:stock`) : ''" @change="(n: number | undefined) => setStock(row.sku, warehouse.warehouseId, n)" /></div><small>总库存 {{ row.sku.stock ?? '待设置' }}</small></template></el-table-column>
              <el-table-column label="平台 SKU（货号）" min-width="140"><template #default="{ row }"><div :data-hint="`sku:${row.key}:itemNum`" :title="hints[`sku:${row.key}:itemNum`]?.source"><el-input v-model="row.sku.itemNum" :placeholder="hintPlaceholder(`sku:${row.key}:itemNum`)" /></div></template></el-table-column>
              <el-table-column min-width="140"><template #header>重量 (kg) <el-button link type="primary" @click="batchSet('weight', '重量 (kg)')">批量</el-button></template>
                <template #default="{ row }"><div :data-hint="`sku:${row.key}:weight`" :title="hints[`sku:${row.key}:weight`]?.source"><el-input-number v-model="row.sku.weight" :min="0.001" :max="100" :controls="false" :placeholder="hintPlaceholder(`sku:${row.key}:weight`)" /></div></template></el-table-column>
              <el-table-column label="启用" width="80"><template #default="{ row }"><el-switch v-model="row.sku.isDelete" active-value="0" inactive-value="1" /></template></el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="产品图片" name="images">
            <h4>产品图片（{{ current.content.imgUrls.length }} 张）</h4>
            <p class="muted">勾选图片用于识别、编辑或翻译；第一张为主图。「编辑所选图片」修改勾选的图片；「文字生成新图」只按指令画全新图片，不参考勾选图片。加工结果在「AI 结果」中对比后采纳。</p>
            <div class="image-grid"><div v-for="(url, i) in current.content.imgUrls" :key="url" class="image-card">
              <el-checkbox :model-value="selectedImages.includes(url)" @change="toggleImage(url)">{{ i === 0 ? '主图' : `商品图 ${i + 1}` }}</el-checkbox>
              <el-image :src="url" fit="contain" :preview-src-list="current.content.imgUrls" preview-teleported referrerpolicy="no-referrer" />
              <div class="inline"><el-button size="small" :disabled="i === 0" @click="moveImage(i, -1)">前移</el-button><el-button size="small" :disabled="i === current.content.imgUrls.length - 1" @click="moveImage(i, 1)">后移</el-button><el-button size="small" type="danger" @click="removeImage(url)">移除</el-button></div>
            </div></div>
            <div class="inline"><el-input v-model="newImageUrl" placeholder="添加公网商品图片 URL" /><el-button @click="addImage">添加图片</el-button></div>
            <el-input v-model="imagePrompt" type="textarea" :rows="3" placeholder="编辑所选图片示例：去掉右下角的水印文字，其余内容保持不变；文字生成新图需描述完整画面" />
            <div class="inline ai-actions"><span class="muted">已选 {{ selectedImages.length }} 张</span><el-button :disabled="!config?.configured || !selectedImages.length" @click="ai('ocr')">识别图片文字</el-button>
              <el-button :type="selectedImages.length ? 'primary' : 'default'" :disabled="!imageEnabled || !selectedImages.length || !imagePrompt.trim()" @click="ai('edit')">编辑所选图片</el-button>
              <el-button :disabled="!imageEnabled || !imagePrompt.trim()" @click="ai('generate')">文字生成新图</el-button>
              <el-select v-model="sourceLang" style="width:150px"><el-option value="auto" label="自动识别源语言" /><el-option v-for="(label, code) in languages" :key="code" :value="code" :label="label" /></el-select>
              <el-button :disabled="!imageEnabled || selectedImages.length !== 1" @click="ai('translate')">翻译为 {{ current.language }}</el-button>
            </div>
            <h4>SKU 图片</h4>
            <p v-if="!current.content.skuPropertyList.length" class="muted">没有销售规格；生成 SKU 组合后可为每个规格值设置图片。</p>
            <div v-for="(prop, pi) in current.content.skuPropertyList" :key="`${prop.attrId}-${pi}`" class="sku-images">
              <el-input v-model="prop.attrName" placeholder="规格名称" class="spec-name" />
              <div class="image-grid"><div v-for="value in prop.attrValueList" :key="value.attrValueId" class="image-card sku-image-card">
                <el-input v-model="value.attrValue" placeholder="规格值名称" size="small" />
                <el-image v-if="value.imgUrl" :src="value.imgUrl" fit="contain" referrerpolicy="no-referrer" /><div v-else class="image-empty">未设置图片</div>
                <el-select v-model="value.imgUrl" placeholder="从产品图中选择" clearable size="small"><el-option v-for="(url, index) in current.content.imgUrls" :key="url" :label="index === 0 ? '主图' : `商品图 ${index + 1}`" :value="url" /></el-select>
              </div></div>
            </div>
            <h4>尺寸图表</h4>
            <div class="inline size-chart"><el-image v-if="current.content.sizeChart" :src="current.content.sizeChart" fit="contain" referrerpolicy="no-referrer" /><div v-else class="image-empty">未设置</div>
              <el-input v-model="current.content.sizeChart" placeholder="尺码表图片 URL（服装鞋类等类目需要）" @input="current.content.sizeChartType = current.content.sizeChart ? 'image' : ''" /></div>
          </el-tab-pane>
          <el-tab-pane label="物流与资质" name="package">
            <h4>物流信息</h4>
            <el-form label-position="top" class="attribute-grid">
              <el-form-item label="包裹重量 (kg)" data-hint="weight"><el-input-number v-model="current.content.weight" :min="0.001" :max="100" :controls="false" :placeholder="hintPlaceholder('weight')" /><small v-if="showHint('weight')" class="hint-source">{{ hints.weight.source }}</small></el-form-item>
              <el-form-item v-for="(label, key) in dimensions" :key="key" :label="label" :data-hint="key"><el-input-number v-model="current.content[key]" :min="1" :max="1000" :controls="false" :placeholder="hintPlaceholder(key)" /><small v-if="showHint(key)" class="hint-source">{{ hints[key].source }}</small></el-form-item>
              <el-form-item label="货到付款"><el-switch v-model="current.content.isCodOpen" active-value="1" inactive-value="0" /></el-form-item>
            </el-form>
            <h4>品牌与合规</h4>
            <el-form label-position="top" class="attribute-grid">
              <el-form-item label="品牌 ID（已核实）"><el-input v-model="current.content.brandId" /></el-form-item>
              <el-form-item label="制造商 ID（逗号分隔）"><el-input :model-value="current.content.manufacturerIds.join(',')" @input="(s: string) => current!.content.manufacturerIds = splitIds(s)" /></el-form-item>
              <el-form-item label="责任人 ID（逗号分隔）"><el-input :model-value="current.content.responsiblePersonIds.join(',')" @input="(s: string) => current!.content.responsiblePersonIds = splitIds(s)" /></el-form-item>
            </el-form>
            <el-alert v-if="metadataRequirements" type="info" :closable="false" :title="metadataRequirements" />
            <h4>类目认证文件（真实文件 URL）</h4>
            <p v-if="!certificationRules.length" class="muted">当前类目没有认证要求，或尚未选择类目。</p>
            <div v-for="cert in certificationRules" :key="cert.id" class="inline"><span>{{ cert.name }} {{ cert.isRequired || cert.isMandatory ? '*' : '' }}</span><el-input :model-value="certUrl(cert.id)" placeholder="已核实的认证文件 URL" @input="(url: string) => setCert(cert, url)" /></div>
          </el-tab-pane>
          <el-tab-pane label="AI 结果与同步记录" name="results">
            <el-button @click="loadTasks">刷新任务</el-button>
            <el-empty v-if="!tasks.length" description="尚未提交 AI 或同步任务" />
            <el-card v-for="task in tasks" :key="task.id" class="task-card" shadow="never">
              <template #header><div class="inline"><strong>{{ taskKinds[task.kind] }}</strong><el-tag :type="taskTagTypes[task.status] || 'info'">{{ taskStates[task.status] }}</el-tag><span class="muted">{{ formatTime(task.created_at) }}<template v-if="task.kind !== 'sync' && task.input_version !== current.version"> · 基于较早的草稿内容</template></span></div></template>
              <div v-if="task.operation && (task.operation.image_urls?.length || task.operation.prompt)" class="task-input">
                <div v-if="task.operation.image_urls?.length && !task.result.public_url" class="task-thumbs"><span class="muted">输入图片</span><el-image v-for="url in task.operation.image_urls" :key="url" :src="url" fit="cover" :preview-src-list="task.operation.image_urls" preview-teleported referrerpolicy="no-referrer" /></div>
                <p v-if="task.operation.prompt" class="muted">指令：{{ task.operation.prompt }}</p>
              </div>
              <p v-if="task.error_message" class="error">{{ task.error_message }}</p>
              <p v-if="task.status === 'running' || task.status === 'waiting'" class="muted">{{ stageLabel(task.stage) }}</p>
              <div v-if="task.result.public_url" class="image-comparison"><div v-if="task.kind !== 'generate' && task.result.original_url"><p>原图</p><el-image :src="task.result.original_url" fit="contain" referrerpolicy="no-referrer" /></div><div><p>加工结果 {{ task.result.width }}×{{ task.result.height }}</p><el-image :src="task.result.public_url" fit="contain" :preview-src-list="[task.result.public_url]" preview-teleported referrerpolicy="no-referrer" /></div></div>
              <div v-if="task.kind === 'copy' && task.result.output" class="two-column"><div><h4>当前文案</h4><p>{{ current.content.title }}</p><pre>{{ current.content.notes }}</pre></div><div><h4>候选文案</h4><p>{{ task.result.output.title }}</p><ul><li v-for="bullet in task.result.output.bullet_points" :key="bullet">{{ bullet }}</li></ul><pre>{{ task.result.output.notes }}</pre></div></div>
              <pre v-if="task.kind === 'ocr' && task.result.output">{{ JSON.stringify(task.result.output.blocks, null, 2) }}</pre>
              <ul v-if="task.kind === 'fill' && task.result.output" class="fill-summary">
                <li v-for="line in fillSummary(task.result.output)" :key="line">{{ line }}</li>
                <li class="muted">在「产品属性」「销售属性 / SKU」「物流与资质」的空白字段按 Tab 逐项采纳</li>
              </ul>
              <el-alert v-if="task.result.readback_confirmed" type="success" :closable="false" :title="`${task.result.first_sync ? '已加入' : '已更新'}妙手店铺「${shopName(task.result.shop_id)}」的 TikTok 采集箱，并回读确认`" />
              <p v-if="task.result.skipped?.length" class="muted">未完成、本次未同步（妙手中保持原样）：{{ fieldNames(task.result.skipped) }}</p>
              <el-button v-if="task.kind === 'sync' && task.error_code === 'remote_conflict' && task.id === tasks.find(t => t.kind === 'sync')?.id" type="warning" @click="sync(true)">以草稿内容覆盖妙手中的修改</el-button>
              <p class="muted" v-if="task.result.request_id">模型 {{ task.result.model }} · 请求 {{ task.result.request_id }}</p>
              <div class="inline" v-if="task.status === 'succeeded' && !['sync', 'fill'].includes(task.kind)"><el-tag v-if="task.adopted_version" type="success">已采纳</el-tag>
                <template v-else><el-button v-if="replaceableOriginal(task)" type="primary" @click="replacement[task.id] = task.result.original_url; adopt(task, true)">替换原图（{{ imageLabel(task.result.original_url) }}）</el-button>
                  <el-button :type="replaceableOriginal(task) ? 'default' : 'primary'" @click="adopt(task)">{{ task.result.public_url ? '添加到商品图' : '采纳结果' }}</el-button>
                  <el-select v-if="task.result.public_url" v-model="replacement[task.id]" placeholder="选择要替换的图片" clearable><el-option v-for="url in replaceableImages" :key="url" :value="url" :label="imageLabel(url)" /></el-select>
                  <el-button v-if="task.result.public_url" :disabled="!replacement[task.id]" @click="adopt(task, true)">替换选中图片</el-button></template>
              </div>
              <div class="inline task-actions">
                <el-button v-if="['failed', 'uncertain'].includes(task.status)" @click="retry(task)">{{ retryLabel(task) }}</el-button>
                <el-button v-if="task.operation && imageKinds.includes(task.kind)" @click="reuseInput(task)">复用输入</el-button>
                <el-button v-if="canDelete(task)" type="danger" plain @click="removeTask(task)">删除记录</el-button>
              </div>
            </el-card>
          </el-tab-pane>
          <el-tab-pane label="预览与检查" name="preview">
            <el-alert v-if="dirty" type="warning" :closable="false" title="有未保存修改，请保存后检查。" />
            <el-alert v-if="current.validation?.valid && !dirty" type="success" :closable="false" title="检查通过：资料完整，同步后可在妙手中发布。" />
            <el-alert v-else-if="current.validation?.errors.length && !dirty" type="info" :closable="false" title="以下内容尚未完成。未完成的项不影响同步到妙手采集箱，只是同步时会跳过这些字段（妙手中保持原样）。" />
            <ul v-if="current.validation?.errors.length" class="error"><li v-for="error in current.validation.errors" :key="`${error.field}:${error.message}`">{{ error.message }}</li></ul>
            <h2>{{ current.content.title }}</h2><div class="preview-images"><img v-for="url in current.content.imgUrls" :key="url" :src="url" referrerpolicy="no-referrer" alt="商品图片" /></div>
            <h4>详细描述（同步内容预览）</h4>
            <div class="preview-description">
              <ul v-if="current.content.bullet_points.some(b => b.trim())"><li v-for="bullet in current.content.bullet_points.filter(b => b.trim())" :key="bullet">{{ bullet }}</li></ul>
              <p v-for="(line, i) in current.content.notes.split('\n').filter(l => l.trim())" :key="i">{{ line }}</p>
              <img v-for="url in current.content.descImgUrls" :key="url" :src="url" referrerpolicy="no-referrer" alt="详情图片" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </main>
      <main v-else><el-empty description="选择左侧草稿开始编辑" /></main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workbench, draftStates, taskStates, taskTagTypes, taskKinds, type Draft, type FillSuggestions, type WorkbenchConfig, type WorkbenchOptions, type WorkbenchTask } from '@/api/workbench'
import { buildHints, type Hint, type Pricing } from './workbenchHints'

const props = defineProps<{ market: string; draftId?: string; active: boolean }>()
const rows = ref<Draft[]>([]), current = ref<Draft | null>(null), tasks = ref<WorkbenchTask[]>([])
const config = ref<WorkbenchConfig>(), options = ref<WorkbenchOptions>(), shops = ref<any[]>([])
const saved = ref(''), boundShop = ref<number | null>(null), busy = ref(false), page = ref(1), total = ref(0)
const keyword = ref(''), filterState = ref(''), section = ref('copy'), newImageUrl = ref(''), imagePrompt = ref(''), sourceLang = ref('auto')
const selectedImages = ref<string[]>([]), replacement = ref<Record<string, string>>({})
const languages: Record<string, string> = { en: 'English · en', zh: '中文 · zh', th: '泰语 · th', vi: '越南语 · vi', ms: '马来语 · ms', id: '印尼语 · id', fil: '菲律宾语 · fil', ja: '日语 · ja', ko: '韩语 · ko', de: '德语 · de', es: '西班牙语 · es', fr: '法语 · fr' }
const dimensions = { packageLength: '包装长度 (cm)', packageWidth: '包装宽度 (cm)', packageHeight: '包装高度 (cm)' } as const
function editable(d: Draft) { return JSON.stringify({ content: d.content, shop_id: d.shop_id, language: d.language }) }
const dirty = computed(() => !!current.value && editable(current.value) !== saved.value)
const imageEnabled = computed(() => config.value?.configured && config.value?.miaoshou_configured)
const syncActive = computed(() => tasks.value.some(t => t.kind === 'sync' && ['queued', 'running', 'waiting', 'uncertain'].includes(t.status)))
const productRules = computed(() => options.value?.metadata.categoryProductAttrList || [])
const saleRules = computed(() => options.value?.metadata.categorySaleAttrList || [])
const certificationRules = computed(() => options.value?.metadata.categoryConfig?.productCertifications || [])
const metadataRequirements = computed(() => {
  const cfg = options.value?.metadata.categoryConfig || {}
  return [cfg.sizeChartIsRequired === '1' || cfg.isSizeChartMandatory === '1' ? '需要尺码表' : '', cfg.manufacturerIsRequired === '1' ? '需要制造商' : '', cfg.responsiblePersonIsRequired === '1' ? '需要责任人' : ''].filter(Boolean).join(' · ')
})
const leafCategories = computed(() => {
  const result: any[] = []
  function walk(tree: any, parents: string[] = []) {
    for (const node of Object.values(tree || {}) as any[]) {
      const path = [...parents, node.nameChinese || node.name || String(node.cid)]
      if (['1', 'true', 'yes'].includes(String(node.isLastLevel).toLowerCase())) result.push({ ...node, path: path.join(' / ') })
      walk(node.children, path)
    }
  }
  walk(options.value?.categories)
  return result
})
const warehouseOptions = computed(() => (options.value?.warehouses.shopWarehouseList || []).filter((s: any) => String(s.shopId) === String(current.value?.shop_id)).flatMap((s: any) => s.warehouseList || []).filter((w: any) => !['0', 'false', 'disabled', 'inactive'].includes(String(w.warehouseEffectStatus).toLowerCase())))
const skuRows = computed(() => Object.entries(current.value?.content.skuMap || {}).map(([key, sku]) => ({ key, sku })))
// One draft per product; its shop can change until the draft is synced to that shop (mirrors the API).
const shopLocked = computed(() => !!current.value?.synced_version || syncActive.value)
// Specs not yet linked to one of the category's sale attributes (TikTok only accepts those).
const unmappedSpecs = computed(() => (current.value?.content.skuPropertyList || []).map((prop: any, index: number) => ({ prop, index }))
  .filter(({ prop }) => !saleRules.value.some((r: any) => String(r.attrId) === String(prop.attrId))))
// 基本信息: detail images, source links and 货源属性, mirroring Miaoshou's collect-box editor.
const newDescImageUrl = ref('')
const sourceDescImages = computed(() => suggestions.value?.source.desc_images || [])
const sourceLinks = computed(() => {
  const snapshot = current.value?.source_snapshot || {}
  const detail = snapshot.raw_data?.detail_response?.data?.editCommonCollectBoxDetail
  const links = (detail?.sourceList || []).filter((x: any) => x?.sourceItemUrl).map((x: any) => ({ url: String(x.sourceItemUrl), remark: x.remark || '' }))
  return links.length ? links : snapshot.product_url ? [{ url: String(snapshot.product_url), remark: '' }] : []
})
const replaceableImages = computed(() => [...(current.value?.content.imgUrls || []), ...(current.value?.content.descImgUrls || [])])
function publicImageUrl(text: string) {
  try { const url = new URL(text.trim()); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null } catch { return null }
}
async function copyText(text: string) { try { await navigator.clipboard.writeText(text); ElMessage.success('已复制') } catch { ElMessage.warning('浏览器不允许复制，请手动选择链接') } }
function importDescImages() { if (current.value) current.value.content.descImgUrls = [...sourceDescImages.value] }
function importSourceAttributes() { if (current.value && suggestions.value) current.value.content.sourceAttributes = suggestions.value.source.attributes.filter(a => a.name).map(a => ({ name: a.name, value: a.value })) }
function moveDescImage(i: number, delta: number) { const a = current.value!.content.descImgUrls; [a[i], a[i + delta]] = [a[i + delta], a[i]] }
function removeDescImage(url: string) { current.value!.content.descImgUrls = current.value!.content.descImgUrls.filter(x => x !== url) }
function addDescImage() {
  const url = publicImageUrl(newDescImageUrl.value)
  if (!url || !current.value) { ElMessage.warning('请输入无认证信息的公网图片 URL'); return }
  if (!current.value.content.descImgUrls.includes(url)) current.value.content.descImgUrls.push(url)
  newDescImageUrl.value = ''
}
async function translateImage(url: string) { const previous = selectedImages.value; selectedImages.value = [url]; try { await ai('translate') } finally { selectedImages.value = previous } }
function imageLabel(url: string) {
  const main = current.value?.content.imgUrls.indexOf(url) ?? -1
  if (main >= 0) return main === 0 ? '主图' : `商品图 ${main + 1}`
  const detail = current.value?.content.descImgUrls.indexOf(url) ?? -1
  return detail >= 0 ? `详情图 ${detail + 1}` : '图片'
}
function replaceableOriginal(task: WorkbenchTask) { return !!task.result.public_url && task.kind !== 'generate' && replaceableImages.value.includes(task.result.original_url) }
async function batchSet(field: 'originPrice' | 'price' | 'weight' | 'stock', label: string) {
  if (!current.value) return
  let value: string
  try { ({ value } = await ElMessageBox.prompt(`为全部 ${skuRows.value.length} 个 SKU 设置${label}`, '批量设置', { inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: '请输入数字' })) } catch { return }
  for (const { sku } of skuRows.value) {
    if (field === 'stock') { if (firstWarehouseId.value) setStock(sku, firstWarehouseId.value, Math.floor(Number(value))) }
    else sku[field] = Number(value)
  }
}
function formatTime(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '' }
// Fill suggestions: shown as placeholders in empty fields; Tab (or「采纳全部」) applies them, nothing is automatic.
const suggestions = ref<FillSuggestions>(), pricing = ref<Pricing>({ rate: null, markup: null })
const firstWarehouseId = computed(() => warehouseOptions.value[0]?.warehouseId as string | undefined)
const hints = computed<Record<string, Hint>>(() => current.value ? buildHints(current.value, suggestions.value, { productRules: productRules.value, warehouseId: firstWarehouseId.value, pricing: pricing.value }) : {})
const fillableKeys = computed(() => Object.keys(hints.value).filter(key => hints.value[key].fillable && isEmpty(key)))
const fillActive = computed(() => tasks.value.some(t => t.kind === 'fill' && ['queued', 'running', 'waiting'].includes(t.status)))
const specSuggestion = computed(() => {
  const ai = suggestions.value?.ai
  if (!ai?.cid || ai.cid !== current.value?.content.cid) return []
  return ai.sale_specs.filter(spec => saleRules.value.some((r: any) => String(r.attrId) === spec.attr_id) && !saleValues(spec.attr_id).length)
})
const pricingKey = computed(() => `workbench-pricing:${suggestions.value?.source.currency || 'CNY'}:${current.value?.currency || ''}`)
watch(pricingKey, key => { try { pricing.value = { rate: null, markup: null, ...JSON.parse(localStorage.getItem(key) || '{}') } } catch { pricing.value = { rate: null, markup: null } } }, { immediate: true })
watch(pricing, value => { try { localStorage.setItem(pricingKey.value, JSON.stringify(value)) } catch { /* storage unavailable: keep in memory */ } }, { deep: true })
function parseSkuHint(key: string) { const end = key.lastIndexOf(':'); return { skuKey: key.slice(4, end), field: key.slice(end + 1) } }
function fieldValue(key: string): any {
  const content = current.value!.content as any
  if (key.startsWith('attr:')) return attributeValues(key.slice(5))
  if (key.startsWith('sku:')) {
    const { skuKey, field } = parseSkuHint(key), sku = content.skuMap[skuKey]
    if (!sku) return 'missing'
    return field === 'stock' ? (firstWarehouseId.value ? warehouseStock(sku, firstWarehouseId.value) : 'missing') : sku[field]
  }
  return content[key]
}
function isEmpty(key: string) { const value = fieldValue(key); return value == null || value === '' || (Array.isArray(value) && !value.length) }
function showHint(key: string) { return !!current.value && !!hints.value[key] && isEmpty(key) }
function hintPlaceholder(key: string, fallback = '') {
  const hint = hints.value[key]
  if (!hint || !current.value || !isEmpty(key)) return fallback
  // Narrow SKU cells get the short form; the source is in the cell tooltip.
  return !hint.fillable ? hint.text : key.startsWith('sku:') ? `${hint.text} · Tab` : `建议 ${hint.text} · Tab 填入`
}
async function applyHint(key: string) {
  const hint = hints.value[key]
  if (!current.value || !hint?.fillable || !isEmpty(key)) return
  const content = current.value.content as any
  if (key === 'cid') {
    if (!boundShop.value) { ElMessage.warning('先选择并保存店铺，再采纳建议类目'); return }
    content.cid = hint.value
    await categoryChanged()
  } else if (key.startsWith('attr:')) {
    const rule = productRules.value.find((r: any) => String(r.attrId) === key.slice(5))
    if (rule) setAttribute(rule, hint.value)
  } else if (key.startsWith('sku:')) {
    const { skuKey, field } = parseSkuHint(key), sku = content.skuMap[skuKey]
    if (field === 'stock') setStock(sku, firstWarehouseId.value!, hint.value)
    else sku[field] = hint.value
  } else content[key] = hint.value
}
function onEditorKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return
  const target = event.target as HTMLInputElement | null
  const key = target?.closest<HTMLElement>('[data-hint]')?.dataset.hint
  // Accept like a code completion: only into an empty field with nothing typed; focus still moves on.
  if (key && !String(target?.value ?? '').trim() && hints.value[key]?.fillable && isEmpty(key)) void applyHint(key)
}
async function applyAllHints() {
  const keys = [...fillableKeys.value].sort((a, b) => Number(b === 'cid') - Number(a === 'cid'))
  for (const key of keys) await applyHint(key)
  ElMessage.success(`已填入 ${keys.length} 项建议，请核实后保存`)
}
async function applySpecSuggestion() {
  if (!current.value) return
  const sourceSpecs = suggestions.value?.source.specs || []
  for (const spec of specSuggestion.value) {
    const rule = saleRules.value.find((r: any) => String(r.attrId) === spec.attr_id)
    setSaleAttribute(rule, spec.values.map(v => v.value_id))
    // Carry each source value's image over to the mapped spec value.
    const images = new Map((sourceSpecs.find(s => s.name === spec.source_property)?.values || []).map(v => [v.name, v.image]))
    const prop = current.value.content.skuPropertyList.find((p: any) => String(p.attrId) === spec.attr_id)
    for (const value of prop?.attrValueList || []) if (!value.imgUrl) value.imgUrl = images.get(spec.values.find(v => v.value_id === String(value.attrValueId))?.source_value || '') || ''
  }
  await rebuildSkus()
}
async function loadSuggestions() {
  if (!current.value) return
  const id = current.value.id, result = await workbench.suggestions(id)
  if (current.value?.id === id) suggestions.value = result
}
function fillSummary(output: any) {
  const lines: string[] = []
  if (output.category) lines.push(`类目：${output.category.path}`)
  if (output.weight) lines.push(`商品重量：${output.weight.value} kg（${output.weight.reason}）`)
  if (output.package) lines.push(`包装：${output.package.length}×${output.package.width}×${output.package.height} cm（${output.package.reason}）`)
  if (output.attributes?.length) lines.push(`商品属性：${output.attributes.map((a: any) => a.name).join('、')}`)
  if (output.sale_specs?.length) lines.push(`规格映射：${output.sale_specs.map((s: any) => `${s.source_property} → ${s.name}`).join('、')}`)
  if (output.sku_weights?.length) lines.push(`SKU 重量：${output.sku_weights.length} 项`)
  return lines.length ? lines : ['没有可用建议（来源资料不足或没有匹配的候选类目）']
}
let lastSaved: Draft | null = null
function applyDraft(d: Draft) { lastSaved = structuredClone(d); current.value = structuredClone(d); saved.value = editable(d); boundShop.value = d.shop_id }
function discardChanges() { if (lastSaved) applyDraft(lastSaved) }
async function run(fn: () => Promise<void>) { busy.value = true; try { await fn() } catch { /* request layer reports failures */ } finally { busy.value = false } }
async function loadList() { const r = await workbench.list({ market: props.market, page: page.value, state: filterState.value || undefined, keyword: keyword.value || undefined }); rows.value = r.items; total.value = r.total }
async function search() { page.value = 1; await loadList() }
async function confirmLeave() {
  if (!dirty.value) return true
  // Discard must always be possible, otherwise an unsavable edit traps the operator on this page.
  const choice = await choose(['草稿有未保存修改。保存后离开，或放弃这些修改？', '关闭此窗口可继续编辑。'], '离开当前草稿', '保存并离开', '放弃修改')
  if (choice === 'confirm') return await save()
  if (choice === 'cancel') { discardChanges(); return true }
  return false
}
async function loadShops(market: string) {
  shops.value = []
  if (!config.value?.miaoshou_configured) return
  for (let p = 1; p <= 100; p++) { const r = await workbench.shops(market, p); shops.value.push(...r.items); if (!r.has_more) break }
}
async function open(id: string) {
  if (!(await confirmLeave())) return
  await run(async () => { const d = await workbench.detail(id); applyDraft(d); options.value = undefined; suggestions.value = undefined; selectedImages.value = []; await loadShops(d.market); await loadSuggestions(); await loadTasks(); if (d.shop_id) await loadOptions() })
}
async function save(): Promise<boolean> {
  if (!current.value) return false
  let success = false
  await run(async () => {
    const oldShop = boundShop.value
    const d = await workbench.save(current.value!); applyDraft(d); success = true; await loadList()
    if (oldShop !== d.shop_id) { options.value = undefined; if (d.shop_id) await loadOptions() }
  })
  if (success) ElMessage.success('草稿已保存')
  return success
}
function shopName(id: number | string | null) {
  const shop = shops.value.find(s => String(s.shopId) === String(id))
  return shop?.platformShopName || shop?.shopNick || `店铺 ${id}`
}
async function ensureSaved() { return !dirty.value || await save() }
async function loadOptions() { if (current.value?.shop_id) options.value = await workbench.options(current.value.id, current.value.content.cid) }
async function categoryChanged() {
  if (!current.value || !boundShop.value) return
  const newOptions = await workbench.options(current.value.id, current.value.content.cid)
  options.value = newOptions
  current.value.content.productAttributes = []
  // Existing source variant values remain visible until mapped to the new category.
}
async function check() {
  if (!current.value || !(await ensureSaved())) return
  await run(async () => { applyDraft(await workbench.check(current.value!)); section.value = 'preview'; ElMessage[current.value!.validation?.valid ? 'success' : 'warning'](current.value!.validation?.valid ? '检查通过' : '请补齐检查列表中的资料') })
}
// Sync = save into the shop's Miaoshou TikTok collect box: added the first time, edited afterwards.
const upToDate = computed(() => !!current.value && !dirty.value && current.value.synced_version === current.value.version)
const syncLabel = computed(() => syncActive.value ? '同步中…' : upToDate.value ? '已同步' : current.value?.synced_version ? '更新妙手采集箱' : '同步到妙手采集箱')
const fieldLabels: Record<string, string> = { title: '标题', notes: '详细描述', imgUrls: '产品图片', cid: '类目', productAttributes: '类目属性',
  productCertifications: '认证文件', skuMap: 'SKU', skuPropertyList: '销售规格', weight: '包裹重量', packageLength: '包装长度',
  packageWidth: '包装宽度', packageHeight: '包装高度', sizeChart: '尺码表', sizeChartType: '尺码表', manufacturerIds: '制造商',
  responsiblePersonIds: '责任人', isCodOpen: '货到付款', brandId: '品牌' }
function fieldNames(fields: string[]) { return [...new Set(fields.map(f => fieldLabels[f] || f))].join('、') }
async function sync(overwrite = false) {
  if (!current.value || !(await ensureSaved())) return
  // Check first so the operator sees which unfinished fields this sync will leave as they are in Miaoshou.
  let checked = false
  await run(async () => { applyDraft(await workbench.check(current.value!)); checked = true })
  if (!checked || !current.value) return
  const errors = current.value.validation?.errors || []
  const first = !current.value.synced_version
  const lines = [`将草稿${first ? '加入' : '的修改更新到'}妙手店铺「${shopName(current.value.shop_id)}」的 TikTok 采集箱。`]
  if (errors.length) lines.push(`以下 ${errors.length} 项尚未完成，本次跳过（妙手中保持原样）：`, ...errors.slice(0, 8).map(e => `· ${e.message}`), ...(errors.length > 8 ? [`…等 ${errors.length} 项`] : []))
  else lines.push('资料检查已通过。')
  if (overwrite) lines.push('妙手中对此商品的直接修改将被草稿内容覆盖。')
  const message = h('div', lines.map(line => h('p', { style: 'margin:0 0 4px' }, line)))
  try { await ElMessageBox.confirm(message, first ? '同步到妙手采集箱' : '更新妙手采集箱', { type: overwrite ? 'warning' : 'info', confirmButtonText: overwrite ? '覆盖并同步' : '同步', cancelButtonText: '取消' }) } catch { return }
  await run(async () => { await workbench.sync(current.value!, overwrite); section.value = 'results'; await loadTasks(); ElMessage.success('同步任务已提交') })
}
async function deleteDraft() {
  if (!current.value) return
  const message = current.value.synced_version ? '草稿将从工作台移除。已同步到妙手采集箱的商品不会被删除，仍可在妙手中编辑或发布。确认删除？' : '草稿及未保存的修改将从工作台移除。确认删除？'
  try { await ElMessageBox.confirm(message, '删除草稿', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) } catch { return }
  await run(async () => {
    await workbench.removeDraft(current.value!)
    lastSaved = null; current.value = null; tasks.value = []; suggestions.value = undefined; options.value = undefined
    await loadList(); ElMessage.success('草稿已删除')
  })
}
// Resolves 'confirm' / 'cancel' for the two choices, or null when the dialog is closed.
async function choose(lines: string[], title: string, confirmButtonText: string, cancelButtonText: string) {
  const message = h('div', lines.map(line => h('p', { style: 'margin:0 0 6px' }, line)))
  try { await ElMessageBox.confirm(message, title, { confirmButtonText, cancelButtonText, distinguishCancelAndClose: true, type: 'info' }); return 'confirm' }
  catch (action) { return action === 'cancel' ? 'cancel' : null }
}
async function ai(kind: string) {
  if (!current.value) return
  const count = selectedImages.value.length
  if (kind === 'generate' && count) {
    // Text-to-image never sees the ticked images; editing them is almost always what was meant.
    const choice = await choose([`「文字生成新图」只按指令画一张全新图片，不会参考已勾选的 ${count} 张图片。`, '要修改这些图片（如去水印、换背景），请改用「编辑所选图片」。'], '确认操作', '改为编辑所选图片', '仍然生成新图')
    if (!choice) return
    if (choice === 'confirm') kind = 'edit'
  }
  const images = ['generate', 'copy', 'fill'].includes(kind) ? [] : [...selectedImages.value]
  let batches = [images]
  if (kind === 'edit' && images.length > 1) {
    const choice = await choose([`已选 ${images.length} 张图片，请选择编辑方式：`, `分别编辑：每张图按同一指令各出一张结果（${images.length} 个任务，分别计费）。`, '合成一张：把这些图作为参考合成为一张新图（最多 3 张）。'], '编辑方式', '分别编辑每张', '合成为一张')
    if (!choice) return
    if (choice === 'confirm') batches = images.map(url => [url])
  }
  if (batches.some(b => b.length > 3) && ['ocr', 'edit'].includes(kind)) { ElMessage.warning('每次最多选择三张图片'); return }
  if (!(await ensureSaved())) return
  const prompt = ['copy', 'ocr', 'fill'].includes(kind) ? '' : imagePrompt.value
  await run(async () => {
    try { for (const urls of batches) await workbench.ai(current.value!, kind, urls, prompt, sourceLang.value) }
    finally { if (kind !== 'fill') section.value = 'results'; await loadTasks() }
    ElMessage.success(kind === 'fill' ? 'AI 填充建议生成中，完成后显示在空白字段，按 Tab 采纳'
      : batches.length > 1 ? `已提交 ${batches.length} 个编辑任务，完成后可逐张对比采纳` : 'AI 任务已提交，完成后可对比采纳')
  })
}
async function loadTasks() {
  if (!current.value) return
  const id = current.value.id
  const r = await workbench.tasks(id)
  if (current.value?.id !== id) return
  tasks.value = r.items
  // A newly finished (or deleted) AI fill task changes the suggestions shown in the fields.
  const latestFill = r.items.find(t => t.kind === 'fill' && t.status === 'succeeded')
  if (suggestions.value && (latestFill?.id ?? null) !== (suggestions.value.ai?.task_id ?? null)) await loadSuggestions()
  const latestSync = r.items.find(t => t.kind === 'sync' && t.status === 'succeeded')
  if (latestSync && latestSync.input_version !== current.value.synced_version && !dirty.value) applyDraft(await workbench.detail(id))
}
async function adopt(task: WorkbenchTask, replace = false) {
  if (!current.value || !(await ensureSaved())) return
  const stale = task.input_version !== current.value.version
  if (stale) { try { await ElMessageBox.confirm('该结果基于较早的草稿内容生成，之后草稿已修改。请对比当前内容与候选结果，确认采用？', '采纳较早的结果', { type: 'warning' }) } catch { return } }
  await run(async () => { applyDraft(await workbench.adopt(current.value!, task, stale, replace ? 'replace' : 'append', replacement.value[task.id])); await loadTasks(); await loadList(); ElMessage.success('结果已采纳并保存') })
}
const imageKinds = ['ocr', 'generate', 'edit', 'translate']
// Same keys the worker treats as a saved model result; without one, a retry calls the model again.
function needsModelCall(task: WorkbenchTask) { return task.kind !== 'sync' && !['output', 'image_url', 'upstream_task_id'].some(k => k in task.result) }
function retryLabel(task: WorkbenchTask) { return task.status === 'failed' && needsModelCall(task) && !task.steps.model_started ? '重新执行' : '恢复任务' }
async function retry(task: WorkbenchTask) {
  const model = !!task.steps.model_started && !Object.keys(task.result).length
  const transfer = !!task.steps.transfer_started
  const rerun = !model && !transfer && needsModelCall(task)
  if (task.kind === 'sync' && task.steps.save_started) {
    // An unconfirmed save: re-read only, or explicitly send the save again.
    const choice = await choose(['妙手没有确认上次保存（可能被拒绝或连接中断）。', '重新提交：按当前规则重新准备内容并再次保存到采集箱；同一商品重复保存不会产生新商品。', '仅查询：只读取妙手结果，确认是否已经保存成功。'], '恢复同步', '重新提交保存', '仅查询结果')
    if (!choice) return
    await run(async () => { await workbench.retry(task, false, false, choice === 'confirm'); await loadTasks() })
    return
  }
  const message = model ? '上次模型结果未确认，重新调用可能再次计费。确认重新提交？' : transfer ? '图片转存结果未确认，确认重新转存？已保存模型结果将被复用。'
    : rerun ? '将按原输入重新读取图片并调用模型，会产生一次新的计费。确认重新执行？' : '恢复已保存步骤并查询平台结果？'
  try { await ElMessageBox.confirm(message, retryLabel(task), { type: 'warning' }) } catch { return }
  await run(async () => { await workbench.retry(task, model, transfer); await loadTasks() })
}
// Mirrors the API: running tasks and unconfirmed syncs must stay queryable.
function canDelete(task: WorkbenchTask) { return !['queued', 'running', 'waiting'].includes(task.status) && !(task.kind === 'sync' && task.status === 'uncertain') }
async function removeTask(task: WorkbenchTask) {
  const unadopted = task.status === 'succeeded' && task.kind !== 'sync' && !task.adopted_version
  const message = task.status === 'uncertain' ? '该任务结果未确认，删除后无法再恢复查询或采纳。确认删除记录？'
    : unadopted ? '该结果尚未采纳，删除后无法再采纳。确认删除记录？' : '删除后不再显示此记录，已采纳到草稿的内容不受影响。确认删除？'
  try { await ElMessageBox.confirm(message, '删除记录', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) } catch { return }
  await run(async () => { await workbench.removeTask(task); delete replacement.value[task.id]; await loadTasks(); ElMessage.success('记录已删除') })
}
function reuseInput(task: WorkbenchTask) {
  if (!current.value || !task.operation) return
  const urls = task.operation.image_urls || []
  const available = urls.filter(url => current.value!.content.imgUrls.includes(url))
  selectedImages.value = available
  imagePrompt.value = task.operation.prompt || ''
  if (task.kind === 'translate') sourceLang.value = task.operation.source_lang || 'auto'
  section.value = 'images'
  if (available.length < urls.length) ElMessage.warning(`${urls.length - available.length} 张输入图片已不在当前商品图中，未选中`)
  else ElMessage.success('已填入原任务的图片与指令，可修改后重新提交')
}
function toggleImage(url: string) { selectedImages.value = selectedImages.value.includes(url) ? selectedImages.value.filter(x => x !== url) : [...selectedImages.value, url] }
function addImage() {
  const url = publicImageUrl(newImageUrl.value)
  if (!url || !current.value) { ElMessage.warning('请输入无认证信息的公网图片 URL'); return }
  if (!current.value.content.imgUrls.includes(url)) current.value.content.imgUrls.push(url)
  newImageUrl.value = ''
}
function moveImage(i: number, delta: number) { if (!current.value) return; const a = current.value.content.imgUrls; [a[i], a[i + delta]] = [a[i + delta], a[i]] }
function removeImage(url: string) { if (!current.value) return; current.value.content.imgUrls = current.value.content.imgUrls.filter(x => x !== url); selectedImages.value = selectedImages.value.filter(x => x !== url) }
function attributeValues(id: string) { return (current.value?.content.productAttributes.find(a => String(a.attributeId) === String(id))?.attributeValues || []).map((v: any) => String(v.valueId)) }
function setAttribute(rule: any, ids: string[]) { if (!current.value) return; const value = { attributeId: String(rule.attrId), attributeName: rule.name, attributeValues: ids.map(id => ({ valueId: id, valueName: rule.values?.find((v: any) => String(v.id) === id)?.name || id })) }; current.value.content.productAttributes = [...current.value.content.productAttributes.filter(a => String(a.attributeId) !== String(rule.attrId)), ...(ids.length ? [value] : [])] }
function saleValues(id: string) { return (current.value?.content.skuPropertyList.find(a => String(a.attrId) === String(id))?.attrValueList || []).map((v: any) => String(v.attrValueId)) }
function setSaleAttribute(rule: any, ids: string[]) { if (!current.value) return; const old = current.value.content.skuPropertyList.find(a => String(a.attrId) === String(rule.attrId)); const value = { attrId: String(rule.attrId), attrName: rule.name, attrValueList: ids.map(id => ({ attrValueId: id, attrValue: rule.values?.find((v: any) => String(v.id) === id)?.name || id, imgUrl: old?.attrValueList.find((v: any) => String(v.attrValueId) === id)?.imgUrl || '' })) }; current.value.content.skuPropertyList = [...current.value.content.skuPropertyList.filter(a => a.attrId && String(a.attrId) !== String(rule.attrId)), ...(ids.length ? [value] : [])] }
// SKU key = sorted value ids (numeric first), matching the backend check.
function skuKeyFor(ids: string[]) {
  return ids.length ? ';' + [...ids].sort((a, b) => /^\d+$/.test(a) && /^\d+$/.test(b) ? a.localeCompare(b, 'en', { numeric: true }) : /^\d+$/.test(a) ? -1 : /^\d+$/.test(b) ? 1 : a < b ? -1 : a > b ? 1 : 0).join(';') + ';' : ';'
}
// Link a source spec (e.g. 1688「颜色」) to a sale attribute of the chosen category, keeping its values,
// images and every SKU's price/stock/weight: values match preset names, or stay as custom values.
function mapSpec(index: number, attrId: string) {
  const content = current.value?.content
  const rule = saleRules.value.find((r: any) => String(r.attrId) === attrId)
  if (!content || !rule) return
  if (content.skuPropertyList.some((p: any, i: number) => i !== index && String(p.attrId) === attrId)) { ElMessage.warning(`「${rule.name}」已被其他规格使用`); return }
  const prop = content.skuPropertyList[index], ids = new Map<string, string>(), missing: string[] = []
  const values = prop.attrValueList.map((v: any) => {
    const preset = (rule.values || []).find((x: any) => String(x.name).trim().toLowerCase() === String(v.attrValue).trim().toLowerCase())
    if (!preset && !rule.isCustomized) missing.push(v.attrValue)
    const id = preset ? String(preset.id) : String(v.attrValueId)
    ids.set(String(v.attrValueId), id)
    return { attrValueId: id, attrValue: preset ? preset.name : v.attrValue, imgUrl: v.imgUrl || '' }
  })
  if (missing.length) { ElMessage.warning(`「${rule.name}」只能使用预设值，没有对应：${missing.join('、')}。请在下方「${rule.name}」中手动选择后重新生成 SKU`); return }
  content.skuPropertyList[index] = { attrId, attrName: rule.name, attrValueList: values }
  content.skuMap = Object.fromEntries(Object.entries(content.skuMap).map(([key, sku]) => [skuKeyFor(key.split(';').filter(Boolean).map(id => ids.get(id) ?? id)), sku]))
  ElMessage.success(`已对应到「${rule.name}」，SKU 资料保留。保存后同步即可发送规格与 SKU`)
}
async function rebuildSkus() {
  if (!current.value) return
  let combinations: string[][] = [[]]
  for (const prop of current.value.content.skuPropertyList) { combinations = combinations.flatMap(c => prop.attrValueList.map((v: any) => [...c, String(v.attrValueId)])); if (combinations.length > 200) { ElMessage.warning('最多 200 个 SKU'); return } }
  const old = current.value.content.skuMap
  const keys = combinations.map(skuKeyFor)
  if (Object.keys(old).some(k => !keys.includes(k))) { try { await ElMessageBox.confirm('规格组合已变化，未匹配的 SKU 编辑内容将被移除。确认重建？', '更新 SKU', { type: 'warning' }) } catch { return } }
  current.value.content.skuMap = Object.fromEntries(keys.map(key => [key, old[key] || { itemNum: '', price: null, stock: null, weight: null, isDelete: '0', shopIdToWarehouseIdAndStockMap: {} }]))
}
function skuLabel(key: string) { const names = new Map<string, string>(); for (const prop of current.value?.content.skuPropertyList || []) for (const v of prop.attrValueList) names.set(String(v.attrValueId), v.attrValue); return key === ';' ? '默认规格' : key.split(';').filter(Boolean).map(id => names.get(id) || id).join(' / ') }
function warehouseStock(sku: any, id: string) { return sku.shopIdToWarehouseIdAndStockMap?.[String(current.value?.shop_id)]?.[String(id)] }
function setStock(sku: any, id: string, n: number | undefined) { const shop = String(current.value?.shop_id); sku.shopIdToWarehouseIdAndStockMap ||= {}; sku.shopIdToWarehouseIdAndStockMap[shop] ||= {}; if (n === undefined) delete sku.shopIdToWarehouseIdAndStockMap[shop][String(id)]; else sku.shopIdToWarehouseIdAndStockMap[shop][String(id)] = n; sku.stock = Object.values(sku.shopIdToWarehouseIdAndStockMap[shop]).reduce((sum: number, v: any) => sum + Number(v), 0) }
function splitIds(s: string) { return s.split(',').map(x => x.trim()).filter(Boolean) }
function certUrl(id: string) { return current.value?.content.productCertifications.find(c => String(c.id) === String(id))?.files?.[0]?.fileUrl || '' }
function setCert(cert: any, url: string) { if (!current.value) return; current.value.content.productCertifications = [...current.value.content.productCertifications.filter(c => String(c.id) !== String(cert.id)), ...(url.trim() ? [{ id: String(cert.id), files: [{ fileId: '', fileName: cert.name, fileType: 'document', fileUrl: url.trim() }] }] : [])] }
function stageLabel(stage: string) { return ({ loading_images: '读取输入图片', loading_categories: '读取类目数据', calling_model: '正在调用百炼', translation_poll: '查询图片翻译结果', transferring_image: '转存妙手图片空间', collecting_source: '采集货源并认领平台箱', confirming_shop_claim: '确认目标店铺认领', saving_shop_draft: '保存妙手店铺草稿', confirming_save: '回读核实保存结果' } as Record<string, string>)[stage] || '处理中' }
function beforeUnload(e: BeforeUnloadEvent) { if (dirty.value) { e.preventDefault(); e.returnValue = '' } }
let timer: ReturnType<typeof setInterval> | undefined
onMounted(async () => { config.value = await workbench.config(); await loadList(); if (props.draftId) await open(props.draftId); timer = setInterval(() => { if (props.active && !busy.value && tasks.value.some(t => ['queued', 'running', 'waiting'].includes(t.status))) void loadTasks().catch(() => {}) }, 5000); window.addEventListener('beforeunload', beforeUnload) })
onUnmounted(() => { if (timer) clearInterval(timer); window.removeEventListener('beforeunload', beforeUnload) })
watch(() => props.draftId, id => { if (id && id !== current.value?.id) void open(id) })
watch(() => props.market, () => { page.value = 1; void loadList().catch(() => {}); if (!dirty.value) { current.value = null; tasks.value = [] } })
watch(() => props.active, active => { if (active) void loadList().catch(() => {}) })
onBeforeRouteLeave(() => confirmLeave())
onBeforeRouteUpdate((to, from) => to.query.tab !== from.query.tab ? confirmLeave() : true)
defineExpose({ dirty, confirmLeave, open, loadList })
</script>

<style scoped>
.model-bar,.inline,.editor-toolbar,.binding{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.model-bar{padding:16px 0;font-size:13px;color:var(--el-text-color-secondary)}.workspace{display:grid;grid-template-columns:270px minmax(0,1fr);gap:20px}aside{border:1px solid var(--el-border-color);border-radius:8px;padding:12px;align-self:start}.filters{display:grid;gap:8px;margin-bottom:12px}.draft-row{display:flex;gap:10px;align-items:center;width:100%;text-align:left;background:var(--el-bg-color);border:1px solid var(--el-border-color);border-radius:6px;padding:10px;margin-bottom:8px;cursor:pointer}.draft-row.selected{border-color:var(--app-brand);background:var(--el-color-primary-light-9)}.draft-row img{width:46px;height:46px;object-fit:contain}.draft-row strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:13px}.draft-row small{display:block;color:var(--el-text-color-secondary);margin-top:5px}main{min-width:0;border:1px solid var(--el-border-color);border-radius:8px;padding:20px}.editor-toolbar{position:sticky;top:0;background:var(--el-bg-color);padding:10px 0;z-index:2;border-bottom:1px solid var(--el-border-color-light)}.editor-toolbar>div:first-child{flex:1;min-width:190px}.muted{color:var(--el-text-color-secondary);font-size:13px}.binding{padding-top:18px}.binding .el-form-item{width:230px}.two-column{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}.full{width:100%}.full .inline{margin-bottom:8px}.full .el-input{flex:1}.source-description{white-space:pre-wrap;max-height:250px;overflow:auto}.image-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin:16px 0}.image-card{border:1px solid var(--el-border-color);padding:10px;border-radius:8px}.image-card>.el-image{height:200px;width:100%;margin:10px 0}.ai-actions{margin:16px 0}.image-grid+.inline{margin-bottom:15px}.attribute-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-top:18px}.attribute-grid .el-select,.attribute-grid .el-input-number{width:100%}.sku-table{margin:18px 0}.sku-table .el-input-number{width:100%}.sku-table small{display:block}.warehouse-row{display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:8px}.warehouse-row .el-input-number{width:100px}.fill-bar{margin:14px 0 4px}.source-link{margin:4px 0;word-break:break-all}.desc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin:10px 0}.desc-card{border:1px solid var(--el-border-color);border-radius:6px;padding:6px}.desc-card .el-image{width:100%;height:140px}.desc-card .inline{gap:4px;justify-content:center}.source-attrs{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:8px 16px;margin:10px 0}.source-attr{display:flex;gap:6px;align-items:center}.sku-images{margin-bottom:12px}.sku-images .spec-name{max-width:260px}.sku-image-card{display:grid;gap:6px}.sku-image-card>.el-image,.image-empty{height:140px;width:100%;margin:0}.image-empty{display:flex;align-items:center;justify-content:center;border:1px dashed #cbd5e1;border-radius:6px;color:#94a3b8;font-size:13px}.size-chart>.el-image,.size-chart>.image-empty{width:140px;height:140px;flex:none}.size-chart .el-input{flex:1}.preview-description img{display:block;max-width:100%;margin:6px 0}.hint-source{display:block;color:var(--el-text-color-secondary);font-size:12px;line-height:1.4;margin-top:4px}.pricing{margin:16px 0 4px}.pricing .el-input-number{width:110px}.spec-hint{margin:8px 0}.spec-map{margin-top:8px}.spec-hint span{margin-right:10px}.fill-summary{margin:0;padding-left:18px;line-height:1.8}.task-card{margin:16px 0}.task-input{margin-bottom:12px}.task-input p{margin:6px 0 0;white-space:pre-wrap}.task-thumbs{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.task-thumbs .el-image{width:72px;height:72px;border:1px solid var(--el-border-color);border-radius:4px}.task-actions:empty{display:none}.image-comparison{display:flex;gap:20px;margin-bottom:16px}.image-comparison>div{flex:1}.image-comparison .el-image{height:280px;width:100%}pre{white-space:pre-wrap;word-break:break-word;max-height:420px;overflow:auto;font-size:13px}.error{color:#dc2626}.preview-images{display:flex;flex-wrap:wrap;gap:10px}.preview-images img{width:180px;height:180px;object-fit:contain}@media(max-width:1100px){.workspace{grid-template-columns:1fr}aside{max-height:300px;overflow:auto}.two-column{grid-template-columns:1fr}}@media(max-width:650px){main{padding:12px}.editor-toolbar{position:static}.binding .el-form-item{width:100%}}
</style>
