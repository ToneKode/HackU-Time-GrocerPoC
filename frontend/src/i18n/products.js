// Chinese names for catalog data. [Traditional (HK), Simplified]; size falls back to the English size.
const zh = {
  SKU001: { name: ['Tempo 超柔軟衛生紙 27卷', 'Tempo 超柔软卫生纸 27卷'], size: ['27卷', '27卷'] },
  SKU002: { name: ['唯潔雅 衛生紙 10卷', '唯洁雅 卫生纸 10卷'], size: ['10卷', '10卷'] },
  SKU003: { name: ['舒潔 衛生紙 30卷 大包裝', '舒洁 卫生纸 30卷 大包装'], size: ['30卷', '30卷'] },
  SKU004: { name: ['滴露 多用途表面清潔劑 1L', '滴露 多用途表面清洁剂 1L'] },
  TG001: { name: ['超細纖維清潔布 10件', '超细纤维清洁布 10件'], size: ['10件', '10件'] },
  TG002: { name: ['可疊加收納箱套裝 3件', '可叠加收纳箱套装 3件'], size: ['3件', '3件'] },
  SKU005: { name: ['雜錦零食禮包', '杂锦零食礼包'] },
  TG003: { name: ['卡樂B 原味薯片 105g', '卡乐B 原味薯片 105g'] },
  TG004: { name: ['明治 杏仁朱古力 79g', '明治 杏仁巧克力 79g'] },
  TG005: { name: ['維他 檸檬茶 250ml x 6', '维他 柠檬茶 250ml x 6'] },
  TG006: { name: ['寶礦力水特 500ml x 6', '宝矿力水特 500ml x 6'] },
  TG007: { name: ['飛雪 礦物質水 1.5L x 12', '飞雪 矿物质水 1.5L x 12'] },
  TG008: { name: ['明治 鮮牛奶 2L', '明治 鲜牛奶 2L'] },
  TG009: { name: ['走地雞蛋 10隻', '散养鸡蛋 10枚'], size: ['10隻', '10枚'] },
  TG010: { name: ['嘉頓 生活麥麵包 450g', '嘉顿 生活麦面包 450g'] },
  TG011: { name: ['日清 合味道 海鮮味 5個裝', '日清 合味道 海鲜味 5个装'], size: ['5個', '5个'] },
  TG012: { name: ['金鳳 茉莉香米 5kg', '金凤 茉莉香米 5kg'] },
  TG013: { name: ['李錦記 蠔油 510g', '李锦记 蚝油 510g'] },
  TG014: { name: ['香蕉 1kg', '香蕉 1kg'] },
  TG015: { name: ['富士蘋果 6個', '富士苹果 6个'], size: ['6個', '6个'] },
  TG016: { name: ['西蘭花 500g', '西兰花 500g'] },
  TG017: { name: ['高露潔 全效牙膏 150g x 2', '高露洁 全效牙膏 150g x 2'] },
  TG018: { name: ['海倫仙度絲 洗髮露 750ml', '海飞丝 洗发露 750ml'] },
  TG019: { name: ['多芬 深層滋潤沐浴露 1L', '多芬 深层滋润沐浴露 1L'] },
  TG020: { name: ['幫寶適 乾爽紙尿片 中碼 64片', '帮宝适 干爽纸尿裤 中号 64片'], size: ['64片', '64片'] },
  TG021: { name: ['美素佳兒 金裝 3號奶粉 900g', '美素佳儿 金装 3段奶粉 900g'] },
  TG022: { name: ['必理痛 特效 20粒', '必理痛 特效 20粒'], size: ['20粒', '20粒'] },
  TG023: { name: ['維他命C 1000mg 100粒', '维生素C 1000mg 100粒'], size: ['100粒', '100粒'] },
}

export const storeNamesZh = {
  Watsons: ['屈臣氏', '屈臣氏'],
  HKTVmall: ['HKTVmall', 'HKTVmall'],
  PARKnSHOP: ['百佳', '百佳'],
  'Japan Home Centre': ['日本城', '日本城'],
}

// Fixed policy reasons from the team contract (English) -> [Traditional, Simplified].
export const policyReasonsZh = {
  'Under HK$500 cap': ['低於 HK$500 上限', '低于 HK$500 上限'],
  'Over HK$500 per-transaction cap': ['超過每單 HK$500 上限', '超过每单 HK$500 上限'],
  'Over HK$800 bulk ceiling': ['超過 HK$800 最高金額', '超过 HK$800 最高金额'],
  'Over HK$2000 monthly cap': ['超過每月 HK$2,000 上限', '超过每月 HK$2,000 上限'],
  'Merchant not whitelisted': ['商店不在允許名單內', '商店不在允许名单内'],
  'Merchant blacklisted': ['商店已被封鎖', '商店已被屏蔽'],
  'Category blacklisted': ['此類別已被封鎖', '此类别已被屏蔽'],
}

export default zh
