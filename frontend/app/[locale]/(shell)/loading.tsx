// Loom 路由导航骨架（UX 收口 Q332）：客户侧 shell 导航期间显示；纯静态占位。
import styles from "@/components/loading-skeleton.module.css";

export default function Loading() {
  return (
    <div className={styles.page} aria-busy="true" data-testid="page-loading">
      <div className={styles.titleBar}>
        <span className={styles.skeletonTitle} />
      </div>
      <div className={styles.card}>
        <span className={styles.skeletonLine} style={{ width: "38%" }} />
        <span className={styles.skeletonLine} style={{ width: "72%" }} />
        <span className={styles.skeletonLine} style={{ width: "54%" }} />
      </div>
      <div className={styles.card}>
        <span className={styles.skeletonLine} style={{ width: "88%" }} />
        <span className={styles.skeletonLine} style={{ width: "64%" }} />
        <span className={styles.skeletonLine} style={{ width: "42%" }} />
      </div>
    </div>
  );
}
