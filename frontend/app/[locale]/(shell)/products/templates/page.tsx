import { MenuPlaceholder } from "../../menu-placeholder";
import { ProductsSubnav } from "../products-subnav";

export default function ProductTemplatesPage() {
  return (
    <div>
      <ProductsSubnav />
      <MenuPlaceholder labelKey="products.productTemplates" phase="v1" />
    </div>
  );
}
