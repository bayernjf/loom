import { MenuPlaceholder } from "../../menu-placeholder";
import { ProductsSubnav } from "../products-subnav";

export default function ProductLibraryPage() {
  return (
    <div>
      <ProductsSubnav />
      <MenuPlaceholder labelKey="products.library" phase="v1" />
    </div>
  );
}
