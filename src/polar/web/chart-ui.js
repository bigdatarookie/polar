// Shared chart geometry and stroke identities. No data calculations.
function chartGeometry({height:h,width:w,narrow,rsi,reference,volume=true}) {
  const left=narrow?43:57,right=reference?(narrow?43:60):(narrow?15:22),grid=[];
  if(rsi){
    const gap=24,usable=Math.max(70,h-130),price=Math.floor(usable*.58),vol=Math.floor(usable*.18);
    grid.push({left,right,top:24,height:price+(volume?0:vol+gap)},
      {left,right,top:24+price+gap,height:volume?vol:0},
      {left,right,top:24+price+vol+2*gap,height:usable-price-vol});
  }else grid.push({left,right,top:24,height:Math.max(1,h-(volume?147:68))},
    {left,right,top:h-87,height:volume?43:0});
  return {grid,left,right,rsi,reference,volume,priceBox:{x:left,y:24,width:w-left-right,height:grid[0].height}};
}
function overlayStroke(key,c) {
  const styles={sma:[c.sma,1.8,[2,3]],ema:[c.action,1.8,[7,4]],
    bb_middle:[c.muted,1.1,[1.1,2.2]],bb_upper:[c.equity,1.1,[1.1,2.2]],bb_lower:[c.equity,1.1,[1.1,2.2]],
    rsi:[c.action,1.8,'solid'],asset_reference:[c.equity,2.2,'solid'],benchmark_reference:[c.benchmark,2,[8,4]]};
  const [color,width,type]=styles[key];return {color,width,type};
}
function strokeBackground(stroke){
  if(!Array.isArray(stroke.type))return stroke.color;
  const [ink,gap]=stroke.type;
  return `repeating-linear-gradient(to right, ${stroke.color} 0 ${ink}px, transparent ${ink}px ${ink+gap}px)`;
}
if(typeof module!=='undefined')module.exports={chartGeometry,overlayStroke,strokeBackground};
