export default async function setupReceiptFixture(page) {
  await page.unroute("**/api/**");
  await page.unroute("**/api/v1/**");
  const line = { assignmentId: 1, orderId: 'order-1', orderNo: '407#', skuId: '6942649419550', productName: '云朵探险家护耳帽', propertiesValue: '蔚海蓝 M', quantity: 110, lineId: 1, returnedQuantity: 0, returnableQuantity: 110 };
  const line2 = { ...line, assignmentId: 2, skuId: '6942649419567', propertiesValue: '蔚海蓝 L', quantity: 450, lineId: 2, returnableQuantity: 450 };
  let shipment = { shipmentId: 'issue44', shipmentNo: 'FH20260905-003', status: 'SHIPPED', factoryId: 'test', factoryName: '自动化测试工厂', createdBy: 'test-user', preferredOrderId: null, businessDate: '2026-09-05', note: '', totalBoxes: 5, totalQuantity: 560, createdAt: '2026-09-05T00:00:00Z', submittedAt: '2026-09-05T00:00:00Z', lines: [line, line2], boxes: [
    {boxNo:1,groupKey:null,items:[{...line,boxItemId:1,quantity:10},{...line2,boxItemId:2,quantity:200}]},
    {boxNo:2,groupKey:null,items:[{...line2,boxItemId:3,quantity:50}]},
    {boxNo:3,groupKey:null,items:[{...line,boxItemId:4,quantity:100}]},
    {boxNo:4,groupKey:null,items:[{...line2,boxItemId:5,quantity:100}]},
    {boxNo:5,groupKey:null,items:[{...line2,boxItemId:6,quantity:100}]}
  ], files:[],returnEvents:[],voidRequest:null,receipt:null,receiptDifferences:[] };
  let receipt = {version:0,status:'DRAFT',items:shipment.boxes.flatMap(b=>b.items.map(i=>({boxItemId:i.boxItemId,quantity:i.quantity}))),confirmedAt:null,confirmedByName:null};
  await page.route('**/api/v1/**', async route => {
    const path = route.request().url().split('?')[0].replace(/^https?:\/\/[^/]+/, '');
    const method = route.request().method();
    let data;
    if(path.endsWith('/v1/me')) data={userId:'test-admin',role:'admin',isEnabled:true,isSuperAdmin:true,displayName:'核对管理员',feishuDisplayName:'核对管理员'};
    else if(path.endsWith('/unread-count')) data={unreadCount:0};
    else if(path.includes('/notifications')) data={items:[],total:0};
    else if(path.endsWith('/receipt/confirm')) {
      receipt={...receipt,status:'CONFIRMED',confirmedAt:'2026-09-07T02:00:00Z',confirmedByName:'核对管理员'};
      shipment={...shipment,receipt,boxes:shipment.boxes.map(b=>({...b,items:b.items.map(i=>({...i,quantity:receipt.items.find(x=>x.boxItemId===i.boxItemId).quantity}))}))};
      shipment.lines=shipment.lines.map(l=>({...l,quantity:shipment.boxes.flatMap(b=>b.items).filter(i=>i.assignmentId===l.assignmentId).reduce((a,i)=>a+i.quantity,0)}));
      shipment.totalQuantity=shipment.lines.reduce((a,l)=>a+l.quantity,0);
      data=shipment;
    } else if(path.endsWith('/receipt')) {
      if(method==='PUT') {const body=route.request().postDataJSON();receipt={...receipt,version:receipt.version+1,items:body.items};}
      data=receipt;
    } else if(path.endsWith('/shipments/issue44')) data=shipment;
    else if(path.endsWith('/shipments')) data={items:[shipment],total:1};
    else return route.fulfill({status:404,json:{message:'Unconfigured test endpoint: '+path}});
    return route.fulfill({json:data});
  });
}
