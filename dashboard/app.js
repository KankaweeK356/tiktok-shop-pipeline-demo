/* Interactive, static Decision Dashboard. All finance/model metrics come from JSON report. */
(function () {
  "use strict";
  const $ = s => document.querySelector(s);
  const state = { data:null, evidence:null, evidenceLayer:"source", evidenceTable:"", neonStatus:"not_loaded", neonTables:[], neonTable:"", neonData:null, neonError:"", view:"business", month:"", group:"ALL", sku:"", model:"", week:"", replay:false, rows:[] };
  const names = {
    business:["ภาพรวมธุรกิจ","ยอดขาย กำไร และ KPI ของร้านเสื้อผ้าผู้หญิง","ภาพรวมธุรกิจ"],
    pipeline:["ทดสอบการนำเข้าข้อมูล","เส้นทางข้อมูลจากต้นทางถึงคลังข้อมูลและหลักฐานการตรวจสอบ","การนำเข้าข้อมูล"],
    ml:["พยากรณ์ยอดขาย","ผลทำนายเทียบยอดขายจริงและความน่าเชื่อถือของโมเดล","พยากรณ์ยอดขาย"]
  };
  const groups=["PG01","PG02","PG03","PG04","PG05"];
  const money = (n,digits=0) => n===null||n===undefined||!Number.isFinite(Number(n)) ? "—" :
    new Intl.NumberFormat("th-TH",{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(Number(n));
  const pct=(n,digits=1)=> n===null||n===undefined?"—":money(n,digits)+"%";
  const node=(tag,cls="",label=null)=>{
    const el=document.createElement(tag);
    if(cls)el.className=cls;
    if(label!==null)el.textContent=String(label);
    return el;
  };
  function add(parent,...children){for(const c of children)if(c)parent.append(c);return parent;}
  function box(cls,...children){return add(node("div",cls),...children);}
  function link(text,url){
    const a=node("a","source-link",text+" ↗");a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;
  }
  function small(text,cls="muted"){return node("div","small "+cls,text);}
  function notice(text,warn=false){return box("notice "+(warn?"notice-warning":"notice-info"),node("span","",warn?"⚠":"ⓘ"),node("span","",text));}
  function metric(label,value,description,kind=""){
    return box("metric",node("div","metric-label",label),node("div","metric-value "+kind,value),node("div","metric-sub",description||""));
  }
  function panel(title,description,content,action=null){
    const head=box("panel-head",box("",node("h2","panel-heading",title),description?node("p","panel-description",description):null),action);
    return box("panel",head,content);
  }
  function contentArea(...children){return box("panel-body",...children);}
  function statusLabel(x){
    const good=["PASS","SUCCESS","COMPLETE","READY"].includes(x);
    const bad=["FAIL","INCOMPLETE","INCOMPLETE_COST"].includes(x);
    return node("span","status "+(good?"status-pass":bad?"status-fail":"status-pending"),x||"UNKNOWN");
  }
  function dataTable(columns,rows,formats={}){
    if(!rows || !rows.length)return box("empty-state",node("span","", "ไม่มีข้อมูลในตัวกรองนี้ (ไม่เติมตัวเลขสมมติ)"));
    const table=node("table");
    const thead=node("thead"),hr=node("tr");
    columns.forEach(([key,label])=>add(hr,node("th",formats[key]?.align||"",label)));
    thead.append(hr);table.append(thead);
    const tbody=node("tbody");
    rows.forEach(row=>{
      const tr=node("tr");
      columns.forEach(([key])=>{
        const spec=formats[key]||{};
        const td=node("td",spec.align||"");
        if(spec.kind==="status")td.append(statusLabel(row[key]));
        else if(spec.kind==="money")td.textContent=money(row[key],spec.digits||0);
        else if(spec.kind==="percent")td.textContent=pct(row[key],spec.digits===undefined?1:spec.digits);
        else td.textContent=row[key]===null||row[key]===undefined?"—":String(row[key]);
        tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(tbody);
    return box("table-wrap",table);
  }
  function barChart(data,active=""){
    const list=node("div","bar-list"),max=Math.max(1,...data.map(x=>Number(x.value)||0));
    data.forEach(x=>{
      const track=node("div","bar-track"),fill=node("div","bar-fill"+(x.name===active?" bar-active":""));
      fill.style.width=Math.max(0,Math.min(100,(Number(x.value)||0)/max*100))+"%";
      track.append(fill);
      list.append(box("bar-entry",node("div","bar-title",x.name),track,node("div","bar-value",x.display||money(x.value))));
    });
    return list;
  }
  const title=id=>{
    const group=state.data?.business.groups.find(x=>x.product_group_id===id);
    return group?.product_group_name?id+" · "+group.product_group_name:id;
  };
  function labelInput(labelText,type,value,min,max){
    const label=node("label","field"),title=node("span","",labelText);
    const field=node("input");field.type=type;field.value=value;field.min=min;field.max=max;field.step="0.5";
    add(label,title,field);return {label,field};
  }
  function chooseField(labelText,options,current,handler){
    const label=node("label","field"),select=node("select");
    options.forEach(([id,text])=>{
      const opt=node("option","",text);opt.value=id;
      if(id===current)opt.selected=true;
      select.append(opt);
    });
    select.addEventListener("change",()=>handler(select.value));
    add(label,node("span","",labelText),select);
    return label;
  }

  function fashionThumb(){
    const image=node("img","fashion-preview");
    image.src="./assets/womens-top.svg";
    image.alt="ภาพประกอบเสื้อผู้หญิง ไม่ใช่ภาพสินค้าจริง";
    image.loading="lazy";
    return image;
  }

  function renderBusiness(){
    const d=state.data,months=d.business.months;
    const m=months.find(x=>x.month===state.month)||months[months.length-1];
    const all=d.business.groups.filter(x=>x.month===m.month);
    const shown=state.group==="ALL"?all:all.filter(x=>x.product_group_id===state.group);
    const total=key=>shown.reduce((sum,x)=>sum+Number(x[key]||0),0);
    const rowIncomplete=shown.some(x=>x.contribution_profit===null);
    const allShop=state.group==="ALL";
    const metrics=allShop?[
      metric("ยอดขายสุทธิ","฿"+money(m.net_revenue),m.month),
      metric("ยอดขายเทียบเป้าหมาย",pct(m.revenue_achievement_pct),"เป้าหมาย ฿"+money(m.revenue_target)+" · ทั้งร้าน",Number(m.revenue_achievement_pct)>=100?"metric-good":"metric-bad"),
      metric("กำไรหลังต้นทุนที่เกี่ยวข้อง",m.contribution_profit===null?"—":"฿"+money(m.contribution_profit),m.profit_data_status==="COMPLETE"?"ต้นทุนครบ":"ต้นทุนไม่ครบ"),
      metric("อัตรารักษากำไร",pct(m.profit_protection_rate_pct),"เกณฑ์ "+pct(Number(m.minimum_profit_protection_rate)*100,0)+" ของ Gross Reference",m.profit_protection_status==="PASS"?"metric-good":"metric-bad")
    ]:[
      metric("ยอดขายสุทธิของกลุ่ม","฿"+money(total("net_revenue")),state.group+" · "+m.month),
      metric("ยอดขายก่อนส่วนลด","฿"+money(total("gross_reference_sales")),"ก่อนหักส่วนลด"),
      metric("ค่าโฆษณา","฿"+money(total("ads_cost")),"จาก Group Daily Mart"),
      metric("กำไรกลุ่มสินค้า",rowIncomplete?"—":"฿"+money(total("contribution_profit")),"ไม่ใช่ Profit Protection Gate")
    ];
    const root=$("#app");root.replaceChildren();
    root.append(notice(allShop?"Revenue Target และ Profit Protection ประเมินระดับทั้งร้านต่อเดือน ไม่ใช่ราย Product Group":
      "เลือกดูรายกลุ่ม: ไม่ใช้ Revenue Target และ Profit Protection Gate ของทั้งร้านตัดสินรายกลุ่ม"));
    root.append(add(box("metrics"),...metrics));
    const monthChart=node("div","mini-chart");
    const max=Math.max(1,...months.map(x=>Number(x.net_revenue)));
    months.forEach(x=>{
      const btn=node("button","mini-col");
      btn.type="button";btn.setAttribute("aria-label","ดูเดือน "+x.month);
      btn.title=x.month+" · ฿"+money(x.net_revenue);
      const bar=node("span","mini-bar"+(x.month===m.month?" is-active":""));
      bar.style.height=Math.max(2,Number(x.net_revenue)/max*100)+"%";
      btn.append(bar);
      btn.addEventListener("click",()=>{
        state.month=x.month;$("#monthFilter").value=x.month;renderBusiness();
      });
      monthChart.append(btn);
    });
    const trend=panel("ยอดขายย้อนหลังรายเดือน","คลิกแท่งเพื่อเปลี่ยนเดือน",contentArea(monthChart,
      box("mini-axis",small(months[0].month),small("Net Revenue (บาท)"),small(months[months.length-1].month)),
      small("หมายเหตุ: ตุลาคม 2026 รวม Source Initial Demo ซึ่งมีปริมาณ Order สูงกว่าช่วงย้อนหลัง")));
    const groupBars=shown.map(x=>({name:title(x.product_group_id),value:x.net_revenue,display:"฿"+money(x.net_revenue)}));
    const groupPanel=panel("ยอดขายแยกกลุ่มสินค้า","Net Revenue · "+m.month,contentArea(barChart(groupBars)));
    root.append(box("two-col",trend,groupPanel));
    // Existing DuckDB Sales Fact x Product Dimension; no ad-spend allocation to SKU.
    const skuRows=(d.business.sku_performance||[]).filter(x=>
      x.month===m.month && (state.group==="ALL"||x.product_group_id===state.group)
    ).sort((a,b)=>Number(b.net_revenue)-Number(a.net_revenue));
    if(skuRows.length){
      const choices=[["","เลือก SKU เพื่อดูรายละเอียด"],...skuRows.map(x=>
        [x.sku_id, (x.sku_name||x.sku_id)+" · "+(x.color||"")+" / "+(x.size||"")+" ("+x.sku_id+")"]
      )];
      if(!skuRows.some(x=>x.sku_id===state.sku))state.sku="";
      const picker=chooseField("เจาะลึกสินค้า (SKU)",choices,state.sku,v=>{state.sku=v;renderBusiness()});
      const skuCols=[["sku_id","รหัส SKU"],["sku_name","สินค้า"],["color","สี"],["size","ไซซ์"],
        ["quantity","จำนวนชิ้น"],["net_revenue","ยอดขายสุทธิ"],["contribution_before_group_costs","กำไรก่อนค่าใช้จ่ายระดับกลุ่ม"]];
      const skuFmt={quantity:{align:"text-right"},net_revenue:{kind:"money",align:"text-right"},
        contribution_before_group_costs:{kind:"money",align:"text-right"}};
      const selected=skuRows.find(x=>x.sku_id===state.sku);
      const detail=selected?box("scenario-results",
        box("",fashionThumb(),small("รหัส SKU "+selected.sku_id+" · "+title(selected.product_group_id)),
          node("strong","", "ยอดขาย ฿"+money(selected.net_revenue)+" · "+money(selected.quantity)+" ชิ้น"),
          small("ต้นทุนสินค้า ฿"+money(selected.cogs)+" · ส่วนลดแคมเปญ ฿"+money(selected.campaign_reduction)+
            " · ส่วนลด Voucher ฿"+money(selected.voucher_discount)),
          small("ค่าธรรมเนียม ฿"+money(selected.platform_cost)+" · ค่าจัดส่ง ฿"+money(selected.fulfillment_cost)+
            " · ค่านายหน้า ฿"+money(selected.affiliate_cost)),
          small("กำไรก่อน Ads / Sample / Claim ฿"+money(selected.contribution_before_group_costs))),
        notice("กำไร SKU นี้ยังไม่ได้หักโฆษณาและต้นทุนระดับกลุ่ม ไม่ใช่กำไรสุทธิหลังค่าโฆษณา")
      ):small("เลือก SKU ด้านบนเพื่อดูแยกยอดขาย ส่วนลด ต้นทุน และค่านายหน้า");
      root.append(panel("วิเคราะห์รายสินค้า · Product Group → SKU",
        "อ่านจาก Fact_Sales_Order_Item และ Dim_Product ไม่แก้โครงสร้าง Warehouse",
        contentArea(picker,detail,dataTable(skuCols,skuRows.slice(0,20),skuFmt),
          small("เรียงยอดขายมากไปน้อย แสดง 20 SKU แรกของช่วงที่เลือก · เลือก SKU ด้านบนเพื่อดูตัวอื่นได้"))));
    }
    const adsRows=(d.business.ads_campaigns||[]).filter(x=>
      x.month===m.month && (state.group==="ALL"||x.product_group_id===state.group)
    ).sort((a,b)=>Number(b.ads_spend)-Number(a.ads_spend));
    const creators=(d.business.creator_performance||[]).filter(x=>
      x.month===m.month && (state.group==="ALL"||x.product_group_id===state.group)
    ).sort((a,b)=>Number(b.affiliate_commission)-Number(a.affiliate_commission));
    if(adsRows.length||creators.length)root.append(box("two-col",
      panel("ค่าโฆษณาแยกแคมเปญ",
        "ระดับเดือน × แคมเปญ × กลุ่มสินค้า ไม่ใช่ Ads ราย SKU",
        dataTable([["product_group_id","กลุ่ม"],["ad_campaign_key","รหัสแคมเปญ"],["ads_spend","ค่าโฆษณา"],
          ["impressions","แสดงผล"],["clicks","คลิก"],["conversions","Conversion จาก Source"]],
          adsRows.slice(0,15),{ads_spend:{kind:"money",align:"text-right"}})),
      panel("ยอดขายที่เกี่ยวข้องกับนายหน้า",
        "รวมเฉพาะรายการขายที่มีค่าคอมมิชชัน ไม่บวกยอดขายซ้ำ",
        dataTable([["product_group_id","กลุ่ม"],["creator_key","รหัส Creator"],["associated_sales","ยอดขายที่เกี่ยวข้อง"],
          ["affiliate_commission","ค่านายหน้า"]],creators.slice(0,15),
          {associated_sales:{kind:"money",align:"text-right"},
           affiliate_commission:{kind:"money",align:"text-right"}}))
    ));
    const gov=contentArea(
      box("pipeline-meta",small("Revenue Target: "+m.target_status),small("Profit Status: "+m.profit_protection_status),
        small("Revenue Gap: "+(m.revenue_target===null?"—":"฿"+money(Number(m.net_revenue)-Number(m.revenue_target))))),
      node("div","flow-divider"),
      node("div","callout","สูตร KPI: Revenue Achievement = Net Revenue ÷ Revenue Target; Profit Protection = Contribution Profit ÷ Gross Reference Sales (ยอดก่อนส่วนลด) ทั้งสองเป็น KPI ของทั้งร้านต่อเดือน")
    );
    root.append(panel("KPI Governance · Monthly View","อ่านจาก View_Shop_Monthly_KPI จริง",gov,link("ER2 Schema",d.links.schema)));
    const cols=[["product_group_id","Product Group"],["net_revenue","Net Revenue"],["gross_reference_sales","ยอดขายก่อนส่วนลด"],["ads_cost","ค่าโฆษณา"],["campaign_reduction","Campaign Reduction"],["contribution_profit","กำไรหลังต้นทุนที่เกี่ยวข้อง"]];
    const fmt={};
    cols.slice(1).forEach(x=>fmt[x[0]]={kind:"money",align:"text-right"});
    root.append(panel("ผลการดำเนินงานแยกกลุ่มสินค้า","Grain = Month × Group · ไม่ JOIN Ads ซ้ำกับ SKU",dataTable(cols,shown,fmt)));
    renderScenario(root);
    state.rows=shown;
  }

  function renderScenario(root){
    const d=state.data;
    const panelBody=node("div","panel-body");
    panelBody.append(notice("Sandbox นี้เปลี่ยนตัวเลขแผนได้ แต่ไม่มีโมเดล Causal/Counterfactual ที่รองรับการคำนวณยอดขายหรือ ROI จากการปรับ Ads และส่วนลด",true));
    const choices=chooseField("Product Group",groups.map(id=>[id,title(id)]),state.group==="ALL"?"PG01":state.group,()=>reset());
    const ads=labelInput("Planned Ads ต่อสัปดาห์ (บาท)","number","0","0","1000000");
    const discount=labelInput("ส่วนลด Campaign เฉลี่ย (%)","number","0","0","100");
    const grid=box("scenario-grid",choices,ads.label,discount.label);
    const summary=node("strong","", "—"),explanation=small("เป็นเพียงการเปรียบเทียบแผน ไม่ใช่การพยากรณ์ยอดขายหรือกำไร"),resetButton=node("button","button button-outline","รีเซ็ตค่า");
    resetButton.type="button";
    const result=box("scenario-results",box("",small("แผนอ้างอิงสัปดาห์ "+d.scenario.reference_week),summary,explanation),resetButton);
    const ref=()=>d.scenario.reference_plans.find(x=>x.product_group_id===choices.querySelector("select").value);
    function update(){
      const value=Number(ads.field.value),disc=Number(discount.field.value);
      if(ads.field.value===""||discount.field.value===""||!Number.isFinite(value)||value<0||!Number.isFinite(disc)||disc<0||disc>100){
        summary.textContent="กรุณากรอกงบ ≥0 และส่วนลด 0–100%";return;
      }
      const difference=value-Number(ref()?.planned_ads_week||0);
      summary.textContent="งบ ฿"+money(value)+" ("+(difference>=0?"+":"")+money(difference)+" จากแผนเดิม) · ส่วนลด "+pct(disc);
    }
    function reset(){
      ads.field.value=Number(ref()?.planned_ads_week||0).toFixed(0);
      discount.field.value=(Number(ref()?.planned_discount_mean_week||0)*100).toFixed(1);
      update();
    }
    choices.querySelector("select").addEventListener("change",reset);
    ads.field.addEventListener("input",update);discount.field.addEventListener("input",update);
    resetButton.addEventListener("click",reset);
    add(panelBody,grid,result);
    root.append(panel("ทดลองวางแผนการตลาด","ทดลองกรอกแผนได้ แต่ยังไม่ได้รัน Scenario Forecast",panelBody));
    reset();
  }

  function renderEvidenceExplorer(root){
    const evidence=state.evidence;
    if(!evidence){
      root.append(panel("สำรวจตารางและไฟล์ของแต่ละชั้นข้อมูล",
        "ยังไม่มีไฟล์หลักฐานของการรันที่ส่งออกในชุดข้อมูลนี้",
        contentArea(notice("รายชื่อตารางและข้อมูลตัวอย่างจะปรากฏเมื่อ GitHub Actions สร้าง classroom_evidence.json สำเร็จ"))));
      return;
    }
    const labels={source:"ฐานข้อมูลต้นทาง (SQLite)",landing:"Data Lake — Landing",
      raw:"Data Lake — Raw",standardized:"Data Lake — Standardized",
      warehouse:"Data Warehouse (DuckDB)",governance:"Governance",control:"Control"};
    if(!evidence.layers[state.evidenceLayer])state.evidenceLayer="source";
    const list=evidence.layers[state.evidenceLayer]||[];
    const options=Object.entries(labels).map(([key,label])=>
      [key,label+" · "+(evidence.layers[key]||[]).length+" รายการ"]);
    const layerSelect=chooseField("เลือกชั้นข้อมูล",options,state.evidenceLayer,v=>{
      state.evidenceLayer=v;state.evidenceTable="";renderPipeline();
    });
    if(!list.some(x=>x.name===state.evidenceTable))
      state.evidenceTable=list[0]?.name||"";
    const datasetSelect=chooseField("เลือกตาราง/ชุดข้อมูล",
      list.map(x=>[x.name,x.name+(x.batch?" · "+x.batch:"")]),
      state.evidenceTable,v=>{state.evidenceTable=v;renderPipeline()});
    const item=list.find(x=>x.name===state.evidenceTable)||list[0];
    const details=item?box("scenario-results",box("",
      small("รูปแบบ: "+item.type+(item.batch?" · รอบ "+item.batch:"")),
      node("strong","",item.name),
      small("จำนวนรายการ: "+(item.records===undefined?"—":money(item.records))+
        " · คอลัมน์: "+(item.columns?.length??"—")),
      small("ตำแหน่งข้อมูล: "+(item.path||"Query จากฐานข้อมูลชั่วคราวใน Runner"))
    )):small("ไม่พบรายการข้อมูลในชั้นนี้");
    const headers=(item?.columns||[]).slice(0,8).map(key=>[key,key]);
    const preview=item?.preview?.length?dataTable(headers,item.preview):small("ไม่มีแถวตัวอย่างหรือเป็นไฟล์ Metadata");
    root.append(panel("สำรวจตารางและไฟล์ของแต่ละชั้นข้อมูล",
      "ดูชื่อชุดข้อมูล โครงสร้างคอลัมน์ และตัวอย่างข้อมูลจากผลรันจริง (Snapshot ไม่ใช่ข้อมูลสด)",
      contentArea(notice("หลักฐานนี้มาจาก SQLite / Parquet / DuckDB ของ GitHub Actions ยังไม่ใช่การ Query Neon โดยตรง",true),
        box("two-col",layerSelect,datasetSelect),details,preview,
        box("h-stack",
          link("ตรวจ Workflow และดาวน์โหลดหลักฐาน","https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/workflows/decision-dashboard-ci.yml"),
          link("เปิด Neon Console (ต้องมีสิทธิ์)","https://console.neon.tech/app/projects")),
        small("โปรเจกต์ Neon demo-pipeline ยังแยกจาก Snapshot นี้ · อย่าตีความว่าข้อมูลตรงกันจนกว่าจะเชื่อมและตรวจยอดจริง"))));
  }

  async function loadNeonEvidence(table=""){
    if(state.neonStatus==="loading")return;
    state.neonStatus="loading";state.neonError="";
    if(state.view==="pipeline")renderPipeline();
    try {
      const url="/api/neon-evidence"+(table?"?table="+encodeURIComponent(table)+"&limit=10":"");
      const response=await fetch(url,{cache:"no-store"});
      const payload=await response.json();
      if(!response.ok || !payload.connected || payload.origin!=="NEON_LIVE")
        throw Error(payload.error || "ยังไม่สามารถอ่าน Neon ได้");
      if(!table){
        state.neonTables=payload.tables;
        state.neonData=null;
        state.neonTable="";
      }else{
        state.neonData=payload;
        state.neonTable=table;
      }
      state.neonStatus="ready";
    }catch(error){
      state.neonStatus="error";
      state.neonError=error.message||"ไม่สามารถติดต่อฐานข้อมูลได้";
    }
    if(state.view==="pipeline")renderPipeline();
  }

  function renderNeonExplorer(root){
    const wrap=contentArea();
    wrap.append(notice("ข้อมูลส่วนนี้อ่านจาก Neon Branch demo-pipeline โดยตรง ผ่าน API แบบอ่านอย่างเดียว ไม่ใช่ Snapshot ของ GitHub Actions"));
    if(state.neonStatus==="loading"){
      wrap.append(small("กำลังตรวจสอบฐานข้อมูล Neon…"));
    }else if(state.neonStatus==="error"){
      wrap.append(notice("ยังเชื่อม Neon ไม่สำเร็จ: "+state.neonError,true));
    }else if(state.neonStatus==="not_loaded"){
      wrap.append(small("กดตรวจสอบเพื่ออ่านรายชื่อตารางจริงจาก Neon"));
    }else{
      wrap.append(small("เชื่อมต่อได้ · Schema demo_er1 · "+state.neonTables.length+" ตาราง · ข้อมูลจำลอง"));
      if(state.neonTables.length){
        wrap.append(chooseField("เลือกตารางใน Neon",
          [["","— เลือกตาราง —"],...state.neonTables.map(t=>[t,t])],
          state.neonTable, name=>{if(name)loadNeonEvidence(name);}));
      }
      const d=state.neonData;
      if(d?.table){
        wrap.append(box("pipeline-meta",
          small("ตาราง: "+d.table),
          small("จำนวน Records: "+money(d.row_count)),
          small("เวลา Query: "+(d.generated_at||"—"))));
        wrap.append(small("โครงสร้างตาราง ("+d.columns.length+" คอลัมน์)"));
        wrap.append(dataTable([["column_name","ชื่อคอลัมน์"],["data_type","ชนิดข้อมูล"]],d.columns.slice(0,35)));
        wrap.append(small("ตัวอย่างข้อมูลสูงสุด "+d.preview_limit+" รายการ"));
        const cols=d.columns.slice(0,8).map(x=>[x.column_name,x.column_name]);
        wrap.append(d.preview_rows.length?dataTable(cols,d.preview_rows):
          small("ตารางนี้ยังไม่มีข้อมูลจริงใน Neon · ขณะนี้ยังไม่ได้รัน Cloud Pipeline"));
      }
    }
    const button=node("button","button button-outline","↻ ตรวจสอบ Neon อีกครั้ง");
    button.type="button";button.disabled=state.neonStatus==="loading";
    button.addEventListener("click",()=>loadNeonEvidence());
    wrap.append(button);
    wrap.append(link("เปิด Neon Console เพื่อตรวจเอง (ต้องมีสิทธิ์)","https://console.neon.tech/app/projects"));
    root.append(panel("เปิดข้อมูลจริงจาก Neon PostgreSQL",
      "โครงสร้างตาราง ตัวอย่างข้อมูล และจำนวนรายการที่ Query จากฐานข้อมูล ณ ขณะนั้น",wrap));
  }

  function renderPipeline(){
    const p=state.data.pipeline,meta=p.history.source||{};
    const root=$("#app");root.replaceChildren();
    root.append(notice("ขณะนี้เป็นผลทดสอบ Pipeline จาก SQLite/DuckDB ใน GitHub Actions ยังไม่ได้อ่านข้อมูลจาก Neon โดยตรง",true));
    renderNeonExplorer(root);
    root.append(add(box("metrics"),
      metric("ฐานข้อมูลต้นทาง · SQLite","25 ตาราง","OLTP Schema"),
      metric("คลังข้อมูล · DuckDB",money(p.physical_warehouse_tables)+" ตาราง","ตารางข้อมูลจริง"),
      metric("Initial Validation",p.initial.passed+"/"+p.initial.checks,"Functional Checks","metric-good"),
      metric("Incremental Validation",p.incremental.passed+"/"+p.incremental.checks,"Functional Checks","metric-good")));
    const name={ingest:"Database",extract:"Landing/Raw",transform:"Standardize",load:"Warehouse",validate:"Reconcile"};
    const flow=node("div","flow-grid");
    p.stages.forEach((stage,i)=>{
      flow.append(box("flow-node"+(stage.status==="SUCCESS"?" is-complete":""),
        small(stage.batch.toUpperCase()+" · "+(i%5+1)+"/5","flow-number"),
        node("strong","",name[stage.stage]||stage.stage),
        small(stage.status+" · "+money(stage.elapsed_seconds,2)+" sec")));
    });
    root.append(panel("เส้นทางการประมวลผลข้อมูล","Initial และ Incremental จาก Batch ที่ตรวจสอบจริง",
      contentArea(flow,node("div","flow-divider"),
        box("pipeline-meta",small("Historical Orders: "+money(meta.historical_orders)),
          small("Ads Records: "+money(meta.historical_ads_rows)),
          small("Marketing Plans: "+money(meta.marketing_plan_rows)),
          small("Synthetic Seed: "+meta.seed))),
      link("GitHub Pipeline CI",state.data.links.pipeline)));
    const checks=[
      {check:"Functional · Initial",measure:p.initial.passed+"/"+p.initial.checks,result:p.initial.failed?"FAIL":"PASS"},
      {check:"Functional · Incremental",measure:p.incremental.passed+"/"+p.incremental.checks,result:p.incremental.failed?"FAIL":"PASS"},
      {check:"Sales ER1 vs Warehouse",measure:money(p.incremental.source_paid_item_count)+" vs "+money(p.incremental.warehouse_sales_item_count),result:p.incremental.source_paid_item_count===p.incremental.warehouse_sales_item_count?"PASS":"FAIL"},
      {check:"Net Revenue ER1 vs Warehouse",measure:"฿"+money(p.incremental.er1_net_revenue,2)+" vs ฿"+money(p.incremental.er2_net_revenue,2),result:Math.abs(p.incremental.er1_net_revenue-p.incremental.er2_net_revenue)<.02?"PASS":"FAIL"},
      {check:"Ads Fact vs Mart Gap",measure:"฿"+money(p.ads_fact_to_mart_difference,2),result:Math.abs(p.ads_fact_to_mart_difference)<.02?"PASS":"FAIL"},
      {check:"Error Recovery · Historical Batch",measure:"ไม่ได้ทดสอบใน Run นี้",result:"NOT_RUN"}
    ];
    const assets=contentArea(
      ...[["Source","Synthetic CSV"],["ER1","SQLite · 25 Tables"],["Data Lake","Landing / Raw / Standardized"],["ER2","DuckDB · "+p.physical_warehouse_tables+" Tables"],["Features","Offline Weekly Parquet"],["Recovery","ตรวจเพิ่มเติมใน Pipeline CI เดิม"]].map(([k,v])=>
        box("listline",node("span","",k),node("strong","",v))),
      node("div","callout","ข้อมูลเป็น Snapshot ของ GitHub Actions ไม่ได้เช็กสถานะเซิร์ฟเวอร์แบบ Live"));
    root.append(box("two-col",
      panel("ตรวจสอบความถูกต้องของข้อมูล","ผลที่ตรวจจาก Database และ Warehouse",dataTable([["check","Check"],["measure","Measured"],["result","Status"]],checks,{result:{kind:"status"}})),
      panel("ชุดข้อมูลและการกำกับข้อมูล","ไม่เพิ่มตาราง ML ใน ER1/ER2",assets)));
    renderEvidenceExplorer(root);
    const line=(p.lineage_sample||[]).map(x=>({
      item:x.Source_Order_Item_ID,source:x.Source,
      er1:x.ER1_Net_Revenue,dwh:x.ER2_Net_Revenue,
      group:x.Product_Group_ID,date:x.Sales_Date_Key
    }));
    root.append(panel("ติดตามที่มาของรายการขาย","Trace จาก Source → SQLite → DuckDB",
      dataTable([["item","Item ID"],["source","Source"],["er1","ER1 Net"],["dwh","DWH Net"],["group","Group"],["date","Date Key"]],line,
        {er1:{kind:"money",digits:2},dwh:{kind:"money",digits:2}}),
      link("Repository Evidence",state.data.links.repo)));
    state.rows=checks;
  }

  function renderML(){
    const ml=state.data.ml,chosen=state.model||ml.registry.selected_model;
    const score=ml.test_metrics.find(x=>x.model===chosen)||{};
    const root=$("#app");root.replaceChildren();
    root.append(notice("Synthetic ML แบบ DEMO ONLY: เปรียบเทียบ Forecast Accuracy ไม่ใช่หลักฐานเชิงเหตุและผลว่าเพิ่ม Ads แล้วขายเพิ่ม",true));
    root.append(add(box("metrics"),
      metric("โมเดลที่เลือกจากผลทดสอบ",ml.registry.selected_model,"ไม่ได้เลือกจาก Test"),
      metric("Group WAPE · "+chosen,pct(score.group_wape_pct,2),"เป้าหมาย ≤20%",score.group_target_20pct?"metric-good":"metric-bad"),
      metric("Shop WAPE · "+chosen,pct(score.shop_wape_pct,2),"เป้าหมาย ≤15%",score.shop_target_15pct?"metric-good":"metric-bad"),
      metric("ชุดข้อมูลฝึกโมเดล",money(ml.backtest.dataset_rows)+" Rows",ml.backtest.weeks+" Weeks × "+ml.backtest.groups+" Groups")));
    const steps=[
      ["01","Data Extraction","CSV / SQLite / Parquet / DuckDB"],
      ["02","EDA","Monthly / Group Analysis"],
      ["03","Preparation","Lag & Planned Features"],
      ["04","Training","Naive + LightGBM x2"],
      ["05","Evaluation","MAE / WAPE / Bias"],
      ["06","Validation","3 Folds + Locked Test"],
      ["07","Serving","Reload Serialized Model"],
      ["08","Monitoring","Error and Alerts"]
    ];
    const stepsGrid=node("div","steps-grid");
    steps.forEach(s=>stepsGrid.append(box("step-card",node("div","step-num",s[0]),node("span","step-name",s[1]),node("div","step-text",s[2]))));
    root.append(panel("ขั้นตอนพัฒนาและตรวจสอบโมเดล (สำหรับผู้สนใจ)","ครบกระบวนการตามบทเรียน · Offline Demonstration",contentArea(stepsGrid)));
    const modelRows=ml.test_metrics.map(m=>({name:m.model,value:m.group_wape_pct,display:pct(m.group_wape_pct,2)}));
    const valRows=ml.model_selection.map(m=>({name:m.model,value:m.validation_group_wape_pct,display:pct(m.validation_group_wape_pct,2)}));
    root.append(box("two-col",
      panel("ความคลาดเคลื่อนการทำนายรายกลุ่ม","Aug–Sep 2026 · ยิ่งต่ำยิ่งดี",contentArea(barChart(modelRows,chosen),small("WAPE ไม่ใช่เปอร์เซ็นต์ความแม่นยำที่นำไปลบจาก 100"))),
      panel("เปรียบเทียบผลประเมินโมเดล","เลือกโมเดลจาก May / June / July",contentArea(barChart(valRows,ml.registry.selected_model)))));
    const byGroup=ml.test_by_group.filter(x=>x.model===chosen&&(state.group==="ALL"||x.product_group_id===state.group));
    const imp=ml.feature_importance.slice(0,8).map(x=>({name:x.feature,value:x.gain,display:money(x.gain)}));
    root.append(box("two-col",
      panel("ความคลาดเคลื่อนแยกกลุ่มสินค้า",chosen,dataTable(
        [["product_group_id","Group"],["wape_pct","WAPE"],["mae_thb_per_week","MAE / Week"],["bias_pct","Bias"]],
        byGroup,{wape_pct:{kind:"percent",digits:2},mae_thb_per_week:{kind:"money"},bias_pct:{kind:"percent"}})),
      panel("Feature Importance · Marketing","Gain: ความสัมพันธ์ ไม่ใช่ผล causal",contentArea(barChart(imp)))));
    const weeks=[...new Set(ml.test_predictions.map(x=>x.forecast_week_start))].sort();
    if(!weeks.includes(state.week))state.week=weeks[weeks.length-1];
    const replayContainer=node("div","panel-body");
    const selector=chooseField("Forecast Week (Monday)",weeks.map(x=>[x,x]),state.week,v=>{
      state.week=v;state.replay=false;renderML();
    });
    const replayButton=node("button","button button-primary","ดูผลพยากรณ์");replayButton.type="button";
    replayButton.addEventListener("click",()=>{state.replay=true;renderML()});
    replayContainer.append(box("h-stack",selector,replayButton));
    const archived=ml.test_predictions.filter(x=>x.model===chosen&&x.forecast_week_start===state.week&&
      (state.group==="ALL"||x.product_group_id===state.group));
    const isServing=chosen===ml.registry.selected_model&&state.week===ml.monitoring.forecast_week;
    const served=state.replay&&isServing?ml.serving_predictions.filter(x=>state.group==="ALL"||x.product_group_id===state.group).map(x=>({
      product_group_id:x.product_group_id,
      actual_net_revenue_week:archived.find(a=>a.product_group_id===x.product_group_id)?.actual_net_revenue_week??null,
      predicted_net_revenue_week:x.predicted_net_revenue_week
    })):archived;
    replayContainer.append(small(state.replay?
      (isServing?"Saved Model Serving Replay · โมเดลถูกโหลดใหม่จริงใน CI":
      "Archived Test Prediction · ไม่ได้เรียก Live Model สำหรับสัปดาห์นี้"):
      "เลือกสัปดาห์และกดปุ่มเพื่อดูผลที่สร้างจาก Pipeline จริง"));
    if(state.replay)replayContainer.append(dataTable(
      [["product_group_id","Group"],["actual_net_revenue_week","Actual"],["predicted_net_revenue_week","Prediction"]],served,
      {actual_net_revenue_week:{kind:"money",digits:2},predicted_net_revenue_week:{kind:"money",digits:2}}));
    else replayContainer.append(box("empty-state",node("span","", "กดดูผล Serving / Prediction เพื่อแสดงการทำนายที่บันทึกไว้")));
    replayContainer.append(node("div","flow-divider"));
    const alerts=ml.monitoring.alerts||[];
    replayContainer.append(box("h-stack",
      node("span","tag "+(alerts.length?"tag-warn":"tag-good"),"Monitoring Replay: "+alerts.length+" Alerts"),
      node("span","tag","Model: "+ml.registry.model_version),
      node("span","tag","Approval: DEMO ONLY")));
    replayContainer.append(small(alerts.length?"Alert: "+alerts.join(", "):"ไม่มี Alert ในสัปดาห์ Replay"));
    replayContainer.append(small("Serving/Monitoring เป็น Offline Replay: ใช้ Actual หลังจากทำนายแล้ว ไม่ใช่ระบบสด"));
    root.append(panel("ผลทำนายและการติดตามโมเดล","เลือกรอบ Backtest แล้วเปิดหลักฐานการทำนาย",replayContainer,link("Workflow",state.data.links.ml)));
    root.append(panel("ตัวอย่างข้อมูลที่ใช้ทำนาย","10 ตัวอย่างจาก "+money(ml.feature_count)+" Weekly Feature Rows",
      dataTable([["as_of_date","As-of"],["forecast_week_start","Forecast"],["product_group_id","Group"],["revenue_last_week","Past Revenue"],["planned_ads_week","Planned Ads"]],
        ml.feature_preview,{revenue_last_week:{kind:"money"},planned_ads_week:{kind:"money"}})));
    state.rows=archived;
  }

  function render(){
    if(!state.data)return;
    if(state.view==="business")renderBusiness();
    if(state.view==="pipeline")renderPipeline();
    if(state.view==="ml")renderML();
    $("#exportCurrent").disabled=!state.rows.length;
  }
  function setView(value){
    if(!names[value])return;
    state.view=value;state.replay=false;
    document.querySelectorAll("[data-view]").forEach(btn=>{
      const active=btn.dataset.view===value;
      btn.classList.toggle("is-active",active);
      if(active)btn.setAttribute("aria-current","page");else btn.removeAttribute("aria-current");
    });
    $("#pageTitle").textContent=names[value][0];
    $("#pageSubtitle").textContent=names[value][1];
    $("#crumbView").textContent=names[value][2];
    $("#monthFilterWrap").classList.toggle("hidden",value!=="business");
    $("#groupFilterWrap").classList.toggle("hidden",value==="pipeline");
    $("#modelFilterWrap").classList.toggle("hidden",value!=="ml");
    render();
    if(value==="pipeline" && state.neonStatus==="not_loaded")loadNeonEvidence();
  }
  function exportCsv(){
    const rows=state.rows;if(!rows.length)return;
    const columns=[...new Set(rows.flatMap(x=>Object.keys(x)))];
    const cell=x=>{
      const s=x===null||x===undefined?"":String(x);
      return /[,\"\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;
    };
    const csv=[columns.map(cell).join(","),...rows.map(x=>columns.map(k=>cell(x[k])).join(","))].join("\r\n");
    const blob=new Blob(["\ufeff",csv],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="tiktok_"+state.view+"_"+state.month+".csv";
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function init(){
    document.querySelectorAll("[data-view]").forEach(btn=>btn.addEventListener("click",()=>setView(btn.dataset.view)));
    $("#exportCurrent").addEventListener("click",exportCsv);
    try {
      const res=await fetch("./data/report.json",{cache:"no-cache"});
      if(!res.ok)throw Error("HTTP "+res.status);
      const d=await res.json();
      if(d.schema_version!=="decision_dashboard_v1" ||
         d.source_classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK" ||
         !Array.isArray(d.business?.months) || !Array.isArray(d.ml?.test_predictions) ||
         !Array.isArray(d.pipeline?.stages) || !d.business.months.length || !d.ml.test_predictions.length)
        throw Error("รูปแบบ Report ไม่ถูกต้องหรือไม่มีข้อมูลจริงจาก Pipeline");
      state.data=d;
      const months=d.business.months.map(x=>x.month);
      state.month=months.includes("2026-10")?"2026-10":months[months.length-1];
      $("#monthFilter").replaceChildren(...months.map(x=>{const opt=node("option","",x);opt.value=x;return opt;}));
      $("#monthFilter").value=state.month;
      $("#groupFilter").replaceChildren(...[["ALL","ทุกกลุ่มสินค้า"],...groups.map(x=>[x,title(x)])].map(x=>{
        const opt=node("option","",x[1]);opt.value=x[0];return opt;
      }));
      state.model=d.ml.registry.selected_model;
      $("#modelFilter").replaceChildren(...d.ml.test_metrics.map(x=>{
        const opt=node("option","",x.model);opt.value=x.model;return opt;
      }));
      $("#modelFilter").value=state.model;
      $("#monthFilter").addEventListener("change",e=>{state.month=e.target.value;render()});
      $("#groupFilter").addEventListener("change",e=>{state.group=e.target.value;state.sku="";render()});
      $("#modelFilter").addEventListener("change",e=>{state.model=e.target.value;state.replay=false;render()});
      $("#snapshotStamp").textContent=d.generated_at_utc?new Intl.DateTimeFormat("th-TH",{
        timeZone:"Asia/Bangkok",year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"
      }).format(new Date(d.generated_at_utc)):"Batch Snapshot";
      $("#headerMode").textContent="รายงานจากการรันล่าสุด · ไม่ใช่ข้อมูลสด";
      $("#footerStatus").textContent=d.source_run;
      $("#repoLink").href=d.links.repo;
      setView("business");
      try {
        const evidenceResponse=await fetch("./data/classroom_evidence.json",{cache:"no-cache"});
        if(evidenceResponse.ok){
          const evidence=await evidenceResponse.json();
          if(evidence.classification==="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
            && evidence.layers?.source && evidence.layers?.warehouse)state.evidence=evidence;
        }
      }catch(_error){
        // Explorer will clearly report that the real evidence snapshot is unavailable.
      }
      if(state.view==="pipeline")renderPipeline();
    } catch(e){
      $("#app").replaceChildren(notice("ไม่สามารถโหลด Report Snapshot: "+e.message+
        " กรุณารัน Python Exporter แล้วเปิดเว็บด้วย HTTP Server ไม่ใช่ file://",true));
      $("#headerMode").textContent="ไม่พบข้อมูลรายงาน";
      $("#exportCurrent").disabled=true;
    }
  }
  init();
})();
