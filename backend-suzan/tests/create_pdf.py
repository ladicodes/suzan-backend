import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def create_dummy_pdf(filename="dummy_price_list.pdf"):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    c.drawString(100, 750, "Business Price List - Test")

    items = [
        ("Rice 50kg", "N50,000"),
        ("Beans 10kg", "N12,000"),
        ("Shoes (Sneakers)", "N15,000"),
        ("T-Shirt", "N5,000"),
        ("Laptop Service", "N10,000")
    ]

    y = 700
    for item, price in items:
        c.drawString(100, y, f"{item} - {price}")
        y -= 20

    c.save()
    print(f"Created {filename}")

if __name__ == "__main__":
    create_dummy_pdf()
