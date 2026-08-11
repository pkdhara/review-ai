"""
Unit tests for TypeScriptCodeParser & Angular structure extraction.
"""

import unittest
from app.services.code_parser.typescript_parser import TypeScriptCodeParser


SAMPLE_ANGULAR_COMPONENT = """
import { Component, OnInit, Input, Output, EventEmitter, inject } from '@angular/core';
import { ProductService } from '../services/product.service';
import { BaseComponent } from '../../shared/base.component';

@Component({
  selector: 'app-product-selection',
  templateUrl: './product-selection.component.html',
  styleUrls: ['./product-selection.component.scss']
})
export class ProductSelectionComponent extends BaseComponent implements OnInit {
  @Input() productId: string = '';
  @Output() selected = new EventEmitter<string>();

  private productService = inject(ProductService);
  isSaving: boolean = false;

  constructor(private fb: FormBuilder, public dialog: MatDialog) {
    super();
  }

  ngOnInit(): void {
    this.loadProducts();
  }

  async loadProducts(): Promise<void> {
    const data = await this.productService.getProducts();
    console.log(data);
  }
}
"""


class TestTypeScriptCodeParser(unittest.TestCase):

    def test_parse_angular_component_structure(self):
        struct = TypeScriptCodeParser.parse_class_structure(SAMPLE_ANGULAR_COMPONENT, "src/app/product-selection.component.ts")

        self.assertEqual(struct["class"], "ProductSelectionComponent")
        self.assertEqual(struct["kind"], "component")
        self.assertIn("@Component", struct["decorators"])
        self.assertEqual(struct["selector"], "app-product-selection")
        self.assertEqual(struct["template_url"], "./product-selection.component.html")
        self.assertEqual(struct["extends"], "BaseComponent")
        self.assertIn("OnInit", struct["implements"])

        # Check injected dependencies
        injected = struct["injected_dependencies"]
        self.assertTrue(any("ProductService" in i for i in injected))
        self.assertTrue(any("FormBuilder" in i for i in injected))
        self.assertTrue(any("MatDialog" in i for i in injected))

        # Check method signatures
        method_names = [m["name"] for m in struct["methods"]]
        self.assertIn("ngOnInit", method_names)
        self.assertIn("loadProducts", method_names)

    def test_extract_method_implementation(self):
        impl = TypeScriptCodeParser.extract_method_implementation(
            SAMPLE_ANGULAR_COMPONENT, "loadProducts", "src/app/product-selection.component.ts"
        )
        self.assertIsNotNone(impl)
        self.assertEqual(impl["method_name"], "loadProducts")
        self.assertIn("getProducts()", impl["body"])

    def test_find_symbols_and_references(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            ts_file = Path(tmp_dir) / "product.component.ts"
            ts_file.write_text(SAMPLE_ANGULAR_COMPONENT)

            symbols = TypeScriptCodeParser.find_symbols_in_repo(tmp_dir, "ProductSelectionComponent")
            self.assertTrue(len(symbols) >= 1)

            refs = TypeScriptCodeParser.find_references_in_repo(tmp_dir, "BaseComponent")
            self.assertTrue(len(refs) >= 1)


if __name__ == "__main__":
    unittest.main()
