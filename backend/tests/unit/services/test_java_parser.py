"""
Unit tests for JavaCodeParser (Standard unittest compatible)
"""

import unittest
from pathlib import Path
from app.services.code_parser.java_parser import JavaCodeParser

SAMPLE_JAVA_CODE = """
package com.freshconcepts.service;

import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class OrderService extends BaseService implements OrderProcessor, Serializable {

    @Autowired
    private OrderRepository orderRepository;

    private final CustomerService customerService;

    public OrderService(OrderRepository orderRepository, CustomerService customerService) {
        this.orderRepository = orderRepository;
        this.customerService = customerService;
    }

    @Override
    public Order createOrder(Order order) {
        if (order == null) {
            throw new IllegalArgumentException("Order cannot be null");
        }
        return orderRepository.save(order);
    }

    public void cancelOrder(Long orderId) {
        Order order = orderRepository.findById(orderId).orElseThrow();
        order.setStatus("CANCELLED");
        orderRepository.save(order);
    }

    private void validateOrder(Order order) {
        // internal validation logic
    }
}
"""


class TestJavaCodeParser(unittest.TestCase):

    def test_parse_class_structure(self):
        struct = JavaCodeParser.parse_class_structure(SAMPLE_JAVA_CODE, "OrderService.java")

        self.assertEqual(struct["package"], "com.freshconcepts.service")
        self.assertEqual(struct["class"], "OrderService")
        self.assertEqual(struct["kind"], "class")
        self.assertIn("@Service", struct["annotations"])
        self.assertEqual(struct["extends"], "BaseService")
        self.assertIn("OrderProcessor", struct["implements"])

        # Verify imports
        self.assertIn("java.util.List", struct["imports"])
        self.assertIn("org.springframework.stereotype.Service", struct["imports"])

        # Verify fields
        fields = {f["name"]: f for f in struct["fields"]}
        self.assertIn("orderRepository", fields)
        self.assertIn("customerService", fields)
        self.assertTrue(fields["customerService"]["final"])

        # Verify constructors
        self.assertEqual(len(struct["constructors"]), 1)
        self.assertEqual(struct["constructors"][0]["name"], "OrderService")

        # Verify methods (signatures extracted, NO body in class structure!)
        method_names = [m["name"] for m in struct["methods"]]
        self.assertIn("createOrder", method_names)
        self.assertIn("cancelOrder", method_names)
        self.assertIn("validateOrder", method_names)

        # Check method details
        create_method = next(m for m in struct["methods"] if m["name"] == "createOrder")
        self.assertEqual(create_method["returnType"], "Order")
        self.assertEqual(create_method["visibility"], "public")
        self.assertIn("@Override", create_method["annotations"])

    def test_extract_method_implementation(self):
        impl = JavaCodeParser.extract_method_implementation(SAMPLE_JAVA_CODE, "createOrder", "OrderService.java")

        self.assertIsNotNone(impl)
        self.assertEqual(impl["method_name"], "createOrder")
        self.assertIn("Order cannot be null", impl["body"])
        self.assertGreater(impl["start_line"], 0)
        self.assertGreaterEqual(impl["end_line"], impl["start_line"])

    def test_extract_method_implementation_not_found(self):
        impl = JavaCodeParser.extract_method_implementation(SAMPLE_JAVA_CODE, "nonExistentMethod", "OrderService.java")
        self.assertIsNone(impl)

    def test_complex_brackets_and_strings(self):
        complex_code = """
package com.example;

public class ComplexService {
    public void processData(List<String> items) {
        // Comment with braces { fake_open } }
        /* Multi-line comment
           { another fake }
        */
        String strWithBraces = "String { with braces } and escaped \\" { \\"";
        char charBrace = '{';

        items.forEach(item -> {
            System.out.println("Lambda brace { " + item);
        });

        Runnable r = new Runnable() {
            @Override
            public void run() {
                System.out.println("Anonymous class { inside }");
            }
        };
        r.run();
    }

    public void anotherMethod() {
        System.out.println("next method");
    }
}
"""
        impl = JavaCodeParser.extract_method_implementation(complex_code, "processData", "ComplexService.java")
        self.assertIsNotNone(impl)
        self.assertEqual(impl["method_name"], "processData")
        self.assertIn("Anonymous class", impl["body"])
        self.assertNotIn("anotherMethod", impl["body"])


    def test_find_references_classification(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_p = tmp_path / "OrderController.java"
            file_p.write_text("""
package com.example;

import com.freshconcepts.service.OrderService;

public class OrderController {
    private OrderService orderService;

    public void handleOrder() {
        orderService.createOrder(null);
    }
}
""")
            refs = JavaCodeParser.find_references_in_repo(str(tmp_path), "OrderService")
            match_types = {r["line_number"]: r["match_type"] for r in refs}
            self.assertEqual(match_types[4], "import")
            self.assertEqual(match_types[7], "usage")

            method_refs = JavaCodeParser.find_references_in_repo(str(tmp_path), "createOrder")
            self.assertEqual(method_refs[0]["match_type"], "usage")
            self.assertEqual(method_refs[0]["line_number"], 10)


if __name__ == "__main__":
    unittest.main()
