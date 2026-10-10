"use client";

import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import {
  getContentDetailAction,
  getScriptRecheckAction,
  getVideoWhitelistMaterialAction,
  createVideoSegmentAction,
  listVideoObjectsAction,
  listVideoSegmentsAction,
  updateVideoSegmentTextAction,
  uploadVideoObjectAction,
  type WhitelistMaterialResult,
} from "./actions";
import styles from "../admin.module.css";

// Q324：video-studio 四屏（管理端内容运营台内嵌，只读）——
// 屏1 白名单信息区：final_id 的六层原料包摘要（Q177 material.json 出口，读闸）。
// 屏2 生成结果区：成品详情 body（=video_ref）与状态（段12 video 载体，Q323）。
// 屏3 分段视图（Q328 D1 甲）：structure/expression 层文本按标点切分的只读
//   分段，不新建分段实体、不臆造时长/镜头/转场；可编辑能力随段12 规格到位
//   后开放（规格【待补】）。
// 屏4 内容清洗区（Q328 D2 甲）：FCW 表达层脚本文本只读 CCR 复检
//   （GET /api/admin/content/{id}/script-recheck），不改文本不落报告，
//   处置仍走既有 CCR 人工 approval；成片语音/字幕复检随段12 转写【待补】。
const MATERIAL_LAYERS = [
  "product",
  "platform",
  "strategy",
  "structure",
  "expression",
  "compliance",
] as const;

function layerCount(layer: Record<string, unknown> | undefined): number {
  if (!layer) return 0;
  return Object.keys(layer).length;
}

// Q328（D1 甲）：递归收集 payload 叶子字符串，按句读标点切分为只读分段。
// 分段仅用于浏览（无时长/镜头/转场等编目字段），不臆造键名。
function leafStrings(value: unknown, out: string[]): void {
  if (typeof value === "string") {
    if (value.trim()) out.push(value.trim());
  } else if (Array.isArray(value)) {
    for (const child of value) leafStrings(child, out);
  } else if (value && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      leafStrings(child, out);
    }
  }
}

function splitSegments(text: string): string[] {
  return text
    .split(/[。！？；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function scriptSegments(pack: Extract<WhitelistMaterialResult, { ok: true }>["pack"]): string[] {
  const raw: string[] = [];
  const structure = pack.layers.structure?.payload;
  const expression = pack.layers.expression?.payload;
  if (structure) leafStrings(structure, raw);
  if (expression) leafStrings(expression, raw);
  const out: string[] = [];
  for (const text of raw) out.push(...splitSegments(text));
  return out;
}

export function VideoStudioIsland({
  contentId,
  finalId,
}: {
  contentId: string;
  finalId: string;
}) {
  const t = useTranslations("admin.contentOps");
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  const [whitelist, setWhitelist] = useState<
    Awaited<ReturnType<typeof getVideoWhitelistMaterialAction>> | null
  >(null);
  const [detail, setDetail] = useState<
    Awaited<ReturnType<typeof getContentDetailAction>> | null
  >(null);
  const [scriptCheck, setScriptCheck] = useState<
    Awaited<ReturnType<typeof getScriptRecheckAction>> | null
  >(null);
  // Q336：分段编目实体（①甲，可编辑）与原片留档（③甲）。
  const [catalog, setCatalog] = useState<
    Awaited<ReturnType<typeof listVideoSegmentsAction>> | null
  >(null);
  const [objects, setObjects] = useState<
    Awaited<ReturnType<typeof listVideoObjectsAction>> | null
  >(null);
  const [newType, setNewType] = useState("body");
  const [newText, setNewText] = useState("");
  const [editText, setEditText] = useState<Record<string, string>>({});
  const [catalogMsg, setCatalogMsg] = useState<string | null>(null);
  const [objectMsg, setObjectMsg] = useState<string | null>(null);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (!next) return;
    if (!whitelist) {
      startTransition(async () => {
        setWhitelist(await getVideoWhitelistMaterialAction(finalId));
      });
    }
    if (!detail) {
      startTransition(async () => {
        setDetail(await getContentDetailAction(contentId));
      });
    }
    if (!catalog) {
      startTransition(async () => {
        setCatalog(await listVideoSegmentsAction(contentId));
      });
    }
    if (!objects) {
      startTransition(async () => {
        setObjects(await listVideoObjectsAction(contentId));
      });
    }
  }

  function reloadCatalog() {
    startTransition(async () => {
      setCatalog(await listVideoSegmentsAction(contentId));
    });
  }

  function reloadObjects() {
    startTransition(async () => {
      setObjects(await listVideoObjectsAction(contentId));
    });
  }

  function submitNewSegment() {
    setCatalogMsg(null);
    startTransition(async () => {
      const result = await createVideoSegmentAction(contentId, newType, newText);
      if (result.ok) {
        setNewText("");
        setCatalogMsg(t("catalogSaved"));
        reloadCatalog();
      } else {
        setCatalogMsg(
          result.status === "missing_role"
            ? t("actorMissingRole")
            : `${t("catalogSaveFailed")} (${String(result.status)})`,
        );
      }
    });
  }

  function submitSegmentText(segmentId: string) {
    setCatalogMsg(null);
    startTransition(async () => {
      const result = await updateVideoSegmentTextAction(
        segmentId,
        editText[segmentId] ?? "",
      );
      if (result.ok) {
        setCatalogMsg(
          result.needsRegen ? t("catalogSavedRegen") : t("catalogSaved"),
        );
        reloadCatalog();
      } else {
        setCatalogMsg(
          result.status === "missing_role"
            ? t("actorMissingRole")
            : `${t("catalogSaveFailed")} (${String(result.status)})`,
        );
      }
    });
  }

  function submitObjectUpload(file: File | null) {
    setObjectMsg(null);
    if (!file) return;
    startTransition(async () => {
      const buffer = await file.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      const result = await uploadVideoObjectAction(
        contentId,
        file.name,
        btoa(binary),
        file.type,
      );
      if (result.ok) {
        setObjectMsg(t("objectUploaded"));
        reloadObjects();
      } else if (result.status === 503) {
        setObjectMsg(t("objectStorageDown"));
      } else {
        setObjectMsg(
          result.status === "missing_role"
            ? t("actorMissingRole")
            : `${t("objectUploadFailed")} (${String(result.status)})`,
        );
      }
    });
  }

  function runScriptCheck() {
    setScriptCheck(null);
    startTransition(async () => {
      setScriptCheck(await getScriptRecheckAction(contentId));
    });
  }

  const segments =
    whitelist && whitelist.ok ? scriptSegments(whitelist.pack) : [];

  return (
    <div>
      <button type="button" className={styles.planChip} onClick={toggle}>
        {t("videoStudioToggle")}
      </button>
      {open ? (
        <div className={styles.provisionForm}>
          <section>
            <h3 className={styles.sectionTitle}>{t("whitelistTitle")}</h3>
            {whitelist === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : whitelist.ok ? (
              <ul className={styles.detailList}>
                {MATERIAL_LAYERS.map((layer) => (
                  <li key={layer}>
                    <span className={styles.metaLine}>
                      {t(`layerName.${layer}`)}: {layerCount(whitelist.pack.layers[layer])}
                    </span>
                  </li>
                ))}
                <li>
                  <span className={styles.metaLine}>
                    {t("whitelistFinal")}: {whitelist.pack.final_id}
                  </span>
                </li>
              </ul>
            ) : (
              <p className={styles.riskMedium}>
                {whitelist.status === 403
                  ? t("actorMissingRole")
                  : t("whitelistLoadFailed")}
              </p>
            )}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("resultTitle")}</h3>
            {detail === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : detail.ok ? (
              <ul className={styles.detailList}>
                <li>
                  <span className={styles.metaLine}>
                    {t("videoRefLabel")}: {detail.content.body ?? t("resultEmpty")}
                  </span>
                </li>
                <li>
                  <span className={styles.metaLine}>
                    {t("statusLabel")}: {detail.content.status}
                  </span>
                </li>
                <li>
                  <span className={styles.metaLine}>{t("videoNoTextReview")}</span>
                </li>
              </ul>
            ) : (
              <p className={styles.riskMedium}>
                {detail.status === 403
                  ? t("actorMissingRole")
                  : t("resultLoadFailed")}
              </p>
            )}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("segmentTitle")}</h3>
            <p className={styles.notice}>{t("segmentIntro")}</p>
            {segments.length === 0 ? (
              <p className={styles.notice}>{t("segmentEmpty")}</p>
            ) : (
              <ol className={styles.detailList}>
                {segments.map((segment, index) => (
                  <li key={`${index}-${segment.slice(0, 8)}`}>
                    <span className={styles.metaLine}>
                      {index + 1}. {segment}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("catalogTitle")}</h3>
            <p className={styles.notice}>{t("catalogIntro")}</p>
            {catalog === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : catalog.ok ? (
              <>
                {catalog.segments.length === 0 ? (
                  <p className={styles.notice}>{t("catalogEmpty")}</p>
                ) : (
                  <ol className={styles.detailList}>
                    {catalog.segments.map((segment) => (
                      <li key={segment.segment_id}>
                        <span className={styles.metaLine}>
                          {segment.seq}. [{segment.type}] {segment.text}
                          {segment.start_ms !== null
                            ? ` (${segment.start_ms}-${segment.end_ms ?? "?"}ms)`
                            : ""}
                        </span>
                        <span className={styles.metaLine}>
                          <input
                            defaultValue={segment.text}
                            onChange={(event) =>
                              setEditText((prev) => ({
                                ...prev,
                                [segment.segment_id]: event.target.value,
                              }))
                            }
                          />
                          <button
                            type="button"
                            className={styles.planChip}
                            disabled={pending}
                            onClick={() => submitSegmentText(segment.segment_id)}
                          >
                            {t("catalogSaveText")}
                          </button>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                <p className={styles.metaLine}>
                  <select
                    value={newType}
                    onChange={(event) => setNewType(event.target.value)}
                  >
                    {["hook", "intro", "body", "climax", "ending", "cta"].map(
                      (type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ),
                    )}
                  </select>
                  <input
                    value={newText}
                    placeholder={t("catalogNewPlaceholder")}
                    onChange={(event) => setNewText(event.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.planChip}
                    disabled={pending || !newText.trim()}
                    onClick={submitNewSegment}
                  >
                    {t("catalogAdd")}
                  </button>
                </p>
              </>
            ) : (
              <p className={styles.riskMedium}>
                {catalog.status === 403
                  ? t("actorMissingRole")
                  : t("catalogLoadFailed")}
              </p>
            )}
            {catalogMsg ? <p className={styles.notice}>{catalogMsg}</p> : null}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("objectTitle")}</h3>
            <p className={styles.notice}>{t("objectIntro")}</p>
            {objects === null ? (
              <p className={styles.notice}>
                {pending ? t("loading") : t("loadPending")}
              </p>
            ) : objects.ok ? (
              <>
                {objects.objects.length === 0 ? (
                  <p className={styles.notice}>{t("objectEmpty")}</p>
                ) : (
                  <ul className={styles.detailList}>
                    {objects.objects.map((obj) => (
                      <li key={obj.object_id}>
                        <span className={styles.metaLine}>
                          {obj.object_key} [{obj.source}]
                          {obj.size_bytes !== null ? ` ${obj.size_bytes}B` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className={styles.metaLine}>
                  <input
                    type="file"
                    accept="video/*"
                    disabled={pending}
                    onChange={(event) =>
                      submitObjectUpload(event.target.files?.[0] ?? null)
                    }
                  />
                </p>
              </>
            ) : (
              <p className={styles.riskMedium}>
                {objects.status === 403
                  ? t("actorMissingRole")
                  : t("objectLoadFailed")}
              </p>
            )}
            {objectMsg ? <p className={styles.notice}>{objectMsg}</p> : null}
          </section>
          <section>
            <h3 className={styles.sectionTitle}>{t("scriptCheckTitle")}</h3>
            <p className={styles.notice}>{t("scriptCheckIntro")}</p>
            <button
              type="button"
              className={styles.planChip}
              onClick={runScriptCheck}
              disabled={pending}
            >
              {t("scriptCheckButton")}
            </button>
            {scriptCheck === null ? null : scriptCheck.ok ? (
              scriptCheck.check.text_present ? (
                <ul className={styles.detailList}>
                  <li>
                    <span className={styles.metaLine}>
                      {t("scriptStatusLabel")}: {scriptCheck.check.status ?? "—"}
                    </span>
                  </li>
                  <li>
                    <span className={styles.metaLine}>
                      {t("textLengthLabel")}: {scriptCheck.check.text_length}
                    </span>
                  </li>
                  <li>
                    <span className={styles.metaLine}>
                      {t("blockRequired")}:{" "}
                      {scriptCheck.check.block_required
                        ? t("blockRequiredYes")
                        : t("blockRequiredNo")}
                    </span>
                  </li>
                  <li>
                    <span className={styles.metaLine}>
                      {t("bansLabel")}:{" "}
                      {scriptCheck.check.bans.length > 0
                        ? scriptCheck.check.bans
                            .map((b) => String(b.word ?? ""))
                            .join("、")
                        : t("bansNone")}
                    </span>
                  </li>
                  <li>
                    <span className={styles.metaLine}>
                      {t("downgradesLabel")}:{" "}
                      {scriptCheck.check.downgrades.length > 0
                        ? scriptCheck.check.downgrades
                            .map((d) => String(d.word ?? ""))
                            .join("、")
                        : t("bansNone")}
                    </span>
                  </li>
                </ul>
              ) : (
                <p className={styles.riskMedium}>{t("scriptNoText")}</p>
              )
            ) : (
              <p className={styles.riskMedium}>
                {scriptCheck.status === 403
                  ? t("actorMissingRole")
                  : t("scriptLoadFailed")}
              </p>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
