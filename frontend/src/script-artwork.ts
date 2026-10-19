const artworkRoot = "/static/assets";

const covers: Record<string, string> = {
  fog_harbor_clocktower: "noir-case-desk.png",
  rainy_night_letter: "script-covers/rainy-night-letter.png",
  last_train: "script-covers/last-train.png",
  deep_sea_echo: "script-covers/deep-sea-echo.png",
  old_house_corridor: "script-covers/old-house-corridor.png",
  silent_theater: "script-covers/silent-theater.png",
};

// Keep a role's portrait identical in the catalog, preparation, and game logs.
const portraits: Record<string, number> = {
  shen_zhiwei: 1, gu_linchuan: 2, zhou_jiming: 3, xu_yanzhou: 4,
  rnl_qin_he: 1, rnl_shen_yu: 4, rnl_lin_mo: 5,
  lt_duan_yan: 2, lt_ren_rui: 4, lt_bai_jing: 5, lt_tao_wen: 1, lt_tang_shu: 3,
  lu_chao: 4, shen_ke: 2, su_wen: 5, chen_cheng: 3,
  jiang_li: 1, jiang_qiao: 2, tang_tang: 5, meng_lan: 6, pei_yan: 3,
  shen_yi: 1, xu_ran: 2, ren_tong: 3, bai_zhi: 5, qiao_man: 6, gan_ji: 4,
};

export function scriptCover(scriptId: string): string {
  return `${artworkRoot}/${covers[scriptId] || "noir-case-desk.png"}`;
}

export function rolePortrait(roleId: string): string {
  if (!roleId || roleId.toLowerCase() === "dm") return "";
  let hash = 2166136261;
  for (const character of roleId) {
    hash = Math.imul(hash ^ character.codePointAt(0)!, 16777619) >>> 0;
  }
  const index = portraits[roleId] || (hash % 6) + 1;
  return `${artworkRoot}/portraits/portrait-${String(index).padStart(2, "0")}.png`;
}
