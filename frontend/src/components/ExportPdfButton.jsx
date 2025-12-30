import React from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";

export default function ExportPdfButton({ targetId = "cc-export" }) {
  const handleExport = async () => {
    const el = document.getElementById(targetId);
    if (!el) {
      alert("Export area not found.");
      return;
    }

    const canvas = await html2canvas(el, { scale: 2, useCORS: true });
    const imgData = canvas.toDataURL("image/png");

    const pdf = new jsPDF("p", "pt", "a4");
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();

    // Fit image to page width
    const imgWidth = pageWidth;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    let y = 0;
    let remaining = imgHeight;

    while (remaining > 0) {
      pdf.addImage(imgData, "PNG", 0, y, imgWidth, imgHeight);
      remaining -= pageHeight;
      if (remaining > 0) {
        pdf.addPage();
        y -= pageHeight;
      }
    }

    pdf.save("consent-companion-diff.pdf");
  };

  return (
    <button className="cc-btn" onClick={handleExport} type="button">
      Export PDF
    </button>
  );
}
