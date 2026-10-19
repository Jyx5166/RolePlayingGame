import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { rolePortrait, scriptCover } from "./script-artwork";

const builtins = ["fog_harbor_clocktower", "rainy_night_letter", "last_train", "deep_sea_echo", "old_house_corridor", "silent_theater"];
const exists = (url: string) => existsSync(new URL(`../assets/${url.replace("/static/assets/", "")}`, import.meta.url));

describe("script artwork identity", () => {
  it("provides different packaged covers and distinct portraits within every built-in cast", () => {
    expect(new Set(builtins.map(scriptCover)).size).toBe(builtins.length);
    for (const id of builtins) {
      const script = JSON.parse(readFileSync(new URL(`../../backend/resources/scripts/${id}.json`, import.meta.url), "utf8"));
      expect(exists(scriptCover(id))).toBe(true);
      const urls = script.roles.map((role: { role_id: string }) => rolePortrait(role.role_id));
      expect(new Set(urls).size).toBe(script.roles.length);
      for (const url of urls) expect(exists(url)).toBe(true);
    }
  });

  it("gives imported roles stable local portraits and keeps the DM identity separate", () => {
    const role = "imported:investigator-新角色";
    expect(rolePortrait(role)).toBe(rolePortrait(role));
    expect(exists(rolePortrait(role))).toBe(true);
    expect(exists(scriptCover("an-imported-script"))).toBe(true);
    expect(rolePortrait("dm")).toBe("");
    expect(rolePortrait("DM")).toBe("");
    expect(rolePortrait("")).toBe("");
  });
});
