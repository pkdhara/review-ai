import { Injectable } from '@angular/core';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import { Finding, Review, ReviewSummary } from '../models/models';

@Injectable({
  providedIn: 'root',
})
export class PdfExportService {

  exportReviewToPdf(
    review: Review | null,
    summary: ReviewSummary | null,
    findings: Finding[]
  ): void {
    const doc = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4',
    });

    const pageWidth = doc.internal.pageSize.getWidth();   // ~210mm
    const pageHeight = doc.internal.pageSize.getHeight(); // ~297mm
    const margin = 14;
    const contentWidth = pageWidth - margin * 2;          // ~182mm
    let y = 0;

    // --- Color Palette ---
    const PRIMARY: [number, number, number] = [79, 70, 229];        // #4F46E5 Indigo
    const PRIMARY_DARK: [number, number, number] = [67, 56, 202];   // #4338CA Deep Indigo
    const TEXT_DARK: [number, number, number] = [15, 23, 42];        // #0F172A Dark Slate
    const TEXT_MUTED: [number, number, number] = [100, 116, 139];    // #64748B Slate Gray
    const BG_LIGHT: [number, number, number] = [248, 250, 252];      // #F8FAFC Light Slate
    const BORDER_COLOR: [number, number, number] = [226, 232, 240];  // #E2E8F0 Light Gray

    const SEVERITY_THEME: Record<string, { barBg: [number, number, number]; bg: [number, number, number]; text: [number, number, number]; border: [number, number, number] }> = {
      critical: { barBg: [220, 38, 38],  bg: [254, 242, 242], text: [185, 28, 28], border: [252, 165, 165] },
      high:     { barBg: [234, 88, 12],  bg: [255, 237, 213], text: [194, 65, 12], border: [253, 186, 116] },
      medium:   { barBg: [202, 138, 4],  bg: [254, 249, 195], text: [161, 98, 7],  border: [253, 224, 71] },
      low:      { barBg: [5, 150, 105],  bg: [236, 253, 245], text: [4, 120, 87],   border: [110, 231, 183] },
      info:     { barBg: [37, 99, 235],  bg: [239, 246, 255], text: [29, 78, 216],  border: [147, 197, 253] },
    };

    // Helper: Clean raw markdown & redundant tags
    const cleanMd = (str?: string): string => {
      if (!str) return '';
      return str
        .replace(/`([^`]+)`/g, '$1')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .trim();
    };

    // Helper: Smart code line wrapper (wraps on whitespace/punctuation, avoiding mid-word breaks)
    const smartWrapCodeLine = (line: string, maxLen: number = 72): string[] => {
      if (!line || line.length <= maxLen) return [line];
      const result: string[] = [];
      let remaining = line;

      while (remaining.length > maxLen) {
        let splitIdx = -1;
        // Search backwards for space, comma, semicolon, bracket, or dot
        for (let i = maxLen; i >= Math.max(0, maxLen - 25); i--) {
          const char = remaining[i];
          if ([' ', ',', ';', '(', ')', '.', '=', '{', '}'].includes(char)) {
            splitIdx = i + 1;
            break;
          }
        }

        // Fallback to hard split if no break character found
        if (splitIdx <= 0) splitIdx = maxLen;

        result.push(remaining.substring(0, splitIdx));
        remaining = remaining.substring(splitIdx);
      }

      if (remaining.length > 0) {
        result.push(remaining);
      }
      return result;
    };

    // Helper: Running Header
    const drawRunningHeader = () => {
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(...TEXT_MUTED);
      const prNumStr = review?.pr_number ? `PR #${review.pr_number}` : 'Review Report';
      doc.text(`ReviewAI Code Analysis — ${prNumStr}`, margin, 12);
      const nowStr = new Date().toLocaleDateString();
      doc.text(nowStr, pageWidth - margin, 12, { align: 'right' });

      doc.setDrawColor(...BORDER_COLOR);
      doc.setLineWidth(0.3);
      doc.line(margin, 14, pageWidth - margin, 14);
    };

    // Helper: Page Break Checker
    const checkPageBreak = (neededHeight: number) => {
      if (y + neededHeight > pageHeight - 18) {
        doc.addPage();
        y = 22; // Padding below running header
        drawRunningHeader();
      }
    };

    // ── 1. Top Decorative Header Banner ────────────────────────────────────────
    doc.setFillColor(...PRIMARY);
    doc.rect(0, 0, pageWidth, 10, 'F');
    doc.setFillColor(...PRIMARY_DARK);
    doc.rect(0, 8, pageWidth, 2, 'F');

    y = 18;

    // Brand Logo Icon & Title Block
    doc.setFillColor(...PRIMARY);
    doc.roundedRect(margin, y, 9, 9, 2, 2, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(7);
    doc.text('AI', margin + 4.5, y + 6, { align: 'center' });

    // Main Title
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.setTextColor(...TEXT_DARK);
    doc.text('ReviewAI', margin + 12, y + 7);

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    doc.setTextColor(...TEXT_MUTED);
    doc.text('Automated Pull Request Code Review Report', margin + 42, y + 6.5);

    // Generation timestamp right aligned
    doc.setFontSize(8.5);
    const dateStr = new Date().toLocaleString();
    doc.text(`Generated: ${dateStr}`, pageWidth - margin, y + 6.5, { align: 'right' });

    y += 14;

    // Header Separator Line
    doc.setDrawColor(...BORDER_COLOR);
    doc.setLineWidth(0.5);
    doc.line(margin, y, pageWidth - margin, y);
    y += 6;

    // ── 2. PR Information Card ───────────────────────────────────────────────────
    const prTitleText = review?.pr_title || `Pull Request #${review?.pr_number || 'N/A'}`;
    const cleanPrTitle = cleanMd(prTitleText);
    const splitPrTitle = doc.splitTextToSize(cleanPrTitle, contentWidth - 14);

    const author = review?.pr_author || review?.author || 'Unknown Author';
    const prNum = review?.pr_number ? `#${review.pr_number}` : 'N/A';
    const repo = review?.repo_slug || review?.bitbucket_repo_slug || 'Repository';
    const jira = review?.jira_key || 'None';

    const metaLine1 = `PR Number: ${prNum}   •   Author: ${author}`;
    const metaLine2 = `Repository: ${repo}   •   Jira Ticket: ${jira}`;

    const splitMeta1 = doc.splitTextToSize(metaLine1, contentWidth - 14);
    const splitMeta2 = doc.splitTextToSize(metaLine2, contentWidth - 14);
    const urlLines = review?.pr_url ? doc.splitTextToSize(`URL: ${review.pr_url}`, contentWidth - 14) : [];

    const prCardHeight = 9 
      + (splitPrTitle.length * 5.2) 
      + (splitMeta1.length * 4.2) 
      + (splitMeta2.length * 4.2) 
      + (urlLines.length > 0 ? (urlLines.length * 4 + 2) : 0);

    // Fill background card
    doc.setFillColor(...BG_LIGHT);
    doc.setDrawColor(...BORDER_COLOR);
    doc.setLineWidth(0.4);
    doc.roundedRect(margin, y, contentWidth, prCardHeight, 2.5, 2.5, 'FD');

    // Left vertical accent bar inset cleanly inside rounded box
    doc.setFillColor(...PRIMARY);
    doc.roundedRect(margin + 0.8, y + 1.5, 2, prCardHeight - 3, 0.8, 0.8, 'F');

    let cardY = y + 5.5;
    // PR Title
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10.5);
    doc.setTextColor(...TEXT_DARK);
    doc.text(splitPrTitle, margin + 6, cardY);
    cardY += (splitPrTitle.length * 5.2) + 1;

    // PR Metadata details
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(...TEXT_MUTED);
    doc.text(splitMeta1, margin + 6, cardY);
    cardY += (splitMeta1.length * 4.2);

    doc.text(splitMeta2, margin + 6, cardY);
    cardY += (splitMeta2.length * 4.2);

    if (urlLines.length > 0) {
      cardY += 1;
      doc.setFontSize(7.5);
      doc.setTextColor(37, 99, 235);
      doc.text(urlLines, margin + 6, cardY);
    }

    y += prCardHeight + 7;

    // ── 3. Executive Assessment Dashboard Cards ───────────────────────────────
    checkPageBreak(35);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(...TEXT_DARK);
    doc.text('Executive Assessment & Risk Dashboard', margin, y);
    y += 5;

    const score = summary?.risk_score ?? review?.risk_score ?? 0;
    let scoreKey = 'low';
    if (score >= 70) scoreKey = 'critical';
    else if (score >= 40) scoreKey = 'high';
    else if (score >= 20) scoreKey = 'medium';

    const scoreTheme = SEVERITY_THEME[scoreKey];
    const cardWidth = (contentWidth - 10) / 3;
    const cardHeight = 24;

    // --- Card 1: Risk Score ---
    doc.setFillColor(...scoreTheme.bg);
    doc.setDrawColor(...scoreTheme.border);
    doc.setLineWidth(0.6);
    doc.roundedRect(margin, y, cardWidth, cardHeight, 2.5, 2.5, 'FD');

    doc.setFontSize(7.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...TEXT_MUTED);
    doc.text('RISK SCORE', margin + cardWidth / 2, y + 6, { align: 'center' });

    doc.setFontSize(15);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...scoreTheme.barBg);
    doc.text(`${Math.round(score)} / 100`, margin + cardWidth / 2, y + 14.5, { align: 'center' });

    doc.setFontSize(7);
    doc.setFont('helvetica', 'bold');
    doc.text(scoreKey.toUpperCase() + ' RISK', margin + cardWidth / 2, y + 20, { align: 'center' });

    // --- Card 2: Recommendation ---
    const rawRec = summary?.overall_recommendation || review?.overall_recommendation || 'NEEDS_DISCUSSION';
    const formattedRec = rawRec.replace(/_/g, ' ');
    let recBg: [number, number, number] = [238, 242, 255];
    let recText: [number, number, number] = PRIMARY;
    let recBorder: [number, number, number] = [199, 210, 254];

    if (rawRec.includes('APPROVE')) {
      recBg = [236, 253, 245];
      recText = [5, 150, 105];
      recBorder = [110, 231, 183];
    } else if (rawRec.includes('REQUEST')) {
      recBg = [254, 242, 242];
      recText = [220, 38, 38];
      recBorder = [252, 165, 165];
    }

    const card2X = margin + cardWidth + 5;
    doc.setFillColor(...recBg);
    doc.setDrawColor(...recBorder);
    doc.roundedRect(card2X, y, cardWidth, cardHeight, 2.5, 2.5, 'FD');

    doc.setFontSize(7.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...TEXT_MUTED);
    doc.text('RECOMMENDATION', card2X + cardWidth / 2, y + 6, { align: 'center' });

    doc.setFontSize(10.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...recText);
    const splitRecHeader = doc.splitTextToSize(formattedRec, cardWidth - 4);
    doc.text(splitRecHeader, card2X + cardWidth / 2, y + 15, { align: 'center' });

    // --- Card 3: Total Findings ---
    const totalCount = summary?.total_findings ?? findings.length;
    const card3X = margin + (cardWidth + 5) * 2;

    doc.setFillColor(...BG_LIGHT);
    doc.setDrawColor(...BORDER_COLOR);
    doc.roundedRect(card3X, y, cardWidth, cardHeight, 2.5, 2.5, 'FD');

    doc.setFontSize(7.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...TEXT_MUTED);
    doc.text('TOTAL FINDINGS', card3X + cardWidth / 2, y + 6, { align: 'center' });

    doc.setFontSize(15);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...TEXT_DARK);
    doc.text(`${totalCount}`, card3X + cardWidth / 2, y + 15, { align: 'center' });

    doc.setFontSize(7);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...TEXT_MUTED);
    doc.text('AI Issues & Defect Items', card3X + cardWidth / 2, y + 20, { align: 'center' });

    y += cardHeight + 8;

    // ── 4. Summary Text Callout ──────────────────────────────────────────────
    if (summary?.summary_text) {
      const cleanSummaryText = cleanMd(summary.summary_text);
      const splitSummary = doc.splitTextToSize(cleanSummaryText, contentWidth - 14);
      const sumBoxHeight = Math.max(16, splitSummary.length * 4.2 + 8);

      checkPageBreak(sumBoxHeight + 6);

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9.5);
      doc.setTextColor(...TEXT_DARK);
      doc.text('Executive Summary Overview', margin, y);
      y += 4;

      doc.setFillColor(...BG_LIGHT);
      doc.setDrawColor(...BORDER_COLOR);
      doc.setLineWidth(0.4);
      doc.roundedRect(margin, y, contentWidth, sumBoxHeight, 2.5, 2.5, 'FD');

      // Left vertical accent bar inset cleanly
      doc.setFillColor(...PRIMARY);
      doc.roundedRect(margin + 0.8, y + 1.5, 2, sumBoxHeight - 3, 0.8, 0.8, 'F');

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8.5);
      doc.setTextColor(...TEXT_DARK);
      doc.text(splitSummary, margin + 6, y + 5.5);

      y += sumBoxHeight + 8;
    }

    // ── 5. Findings Breakdown Table ──────────────────────────────────────────
    checkPageBreak(30);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10.5);
    doc.setTextColor(...TEXT_DARK);
    doc.text('Findings Breakdown by Severity', margin, y);
    y += 4;

    const sevCounts = summary?.findings_by_severity || {
      critical: findings.filter(f => f.severity === 'critical').length,
      high:     findings.filter(f => f.severity === 'high').length,
      medium:   findings.filter(f => f.severity === 'medium').length,
      low:      findings.filter(f => f.severity === 'low').length,
    };

    autoTable(doc, {
      startY: y,
      margin: { left: margin, right: margin },
      head: [['Critical', 'High', 'Medium', 'Low', 'Total Findings']],
      body: [
        [
          `${sevCounts['critical'] || 0}`,
          `${sevCounts['high'] || 0}`,
          `${sevCounts['medium'] || 0}`,
          `${sevCounts['low'] || 0}`,
          `${totalCount}`
        ]
      ],
      theme: 'grid',
      headStyles: {
        fillColor: PRIMARY_DARK,
        textColor: [255, 255, 255],
        fontStyle: 'bold',
        fontSize: 8.5,
        halign: 'center',
        cellPadding: 3,
      },
      bodyStyles: {
        fontSize: 9,
        fontStyle: 'bold',
        halign: 'center',
        textColor: TEXT_DARK,
        cellPadding: 3.5,
      },
      columnStyles: {
        0: { textColor: [220, 38, 38] },
        1: { textColor: [234, 88, 12] },
        2: { textColor: [161, 98, 7] },
        3: { textColor: [5, 150, 105] },
        4: { textColor: PRIMARY_DARK },
      }
    });

    y = (doc as any).lastAutoTable.finalY + 10;

    // ── 6. Detailed Findings Section ─────────────────────────────────────────
    checkPageBreak(25);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.setTextColor(...TEXT_DARK);
    doc.text(`Detailed Review Findings (${findings.length})`, margin, y);
    y += 6;

    if (findings.length === 0) {
      doc.setFont('helvetica', 'italic');
      doc.setFontSize(9);
      doc.setTextColor(...TEXT_MUTED);
      doc.text('No findings or defects identified in this review.', margin, y);
      y += 10;
    } else {
      findings.forEach((finding, index) => {
        const sev = (finding.severity || 'low').toLowerCase();
        const theme = SEVERITY_THEME[sev] || SEVERITY_THEME['low'];

        const rawTitle = cleanMd(finding.title);
        // Remove redundant leading tags like "[Unbounded Query]" if title repeats it
        const cleanTitleText = rawTitle.replace(/^\[[^\]]+\]\s*/, '');
        const splitTitle = doc.splitTextToSize(`${index + 1}. ${cleanTitleText}`, contentWidth - 8);

        const cleanDesc = cleanMd(finding.description);
        const splitDesc = doc.splitTextToSize(cleanDesc, contentWidth - 8);

        const cleanEvidence = finding.evidence ? finding.evidence.trim() : '';

        const cleanRec = cleanMd(finding.recommendation);
        const splitRec = cleanRec ? doc.splitTextToSize(cleanRec, contentWidth - 14) : [];

        const cleanComment = cleanMd(finding.pr_comment || finding.review_comment);
        const splitComment = cleanComment ? doc.splitTextToSize(cleanComment, contentWidth - 14) : [];

        // Header height
        const headerBarHeight = 8;
        const headerBlockNeeded = 22 + (splitTitle.length * 4.8);
        checkPageBreak(headerBlockNeeded);

        // --- Executive Finding Banner ---
        doc.setFillColor(...theme.barBg);
        doc.roundedRect(margin, y, contentWidth, headerBarHeight, 1.5, 1.5, 'F');

        // Badge Text (Left)
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(8);
        doc.setTextColor(255, 255, 255);
        doc.text(`[${sev.toUpperCase()}]`, margin + 4, y + 5.3);

        // Meta (Category • Origin • File Path) Right / Inline
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(7.5);
        
        const categoryStr = (finding.category || 'General').toUpperCase().replace(/_/g, ' ');
        let originStr = '';
        if (finding.origin) {
          switch (finding.origin) {
            case 'introduced_by_pr': originStr = 'PR Introduced'; break;
            case 'modified_by_pr': originStr = 'PR Modified'; break;
            case 'worsened_by_pr': originStr = 'PR Worsened'; break;
            case 'pre_existing': originStr = 'Pre-existing'; break;
            case 'contextual': originStr = 'Contextual'; break;
            default: originStr = finding.origin.replace(/_/g, ' '); break;
          }
        }

        let fileStr = '';
        if (finding.file_path && finding.file_path.trim()) {
          const basename = finding.file_path.split('/').pop() || finding.file_path;
          fileStr = `${basename}${finding.line_number ? ':' + finding.line_number : ''}`;
        }

        let metaText = categoryStr;
        if (originStr) metaText += `  •  ${originStr}`;
        if (fileStr) metaText += `  •  File: ${fileStr}`;

        const truncatedMeta = doc.splitTextToSize(metaText, contentWidth - 32)[0];
        doc.text(truncatedMeta, margin + 28, y + 5.3);

        y += headerBarHeight + 4;

        // --- Finding Title ---
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(10);
        doc.setTextColor(...TEXT_DARK);
        doc.text(splitTitle, margin, y);
        y += (splitTitle.length * 4.8) + 2;

        // --- Description ---
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(8.5);
        doc.setTextColor(51, 65, 85); // Slate 700
        doc.text(splitDesc, margin, y);
        y += (splitDesc.length * 4.0) + 4;

        // --- Smart Code Evidence Snippet ---
        if (cleanEvidence) {
          const rawLines = cleanEvidence.split('\n');
          const wrappedEvLines: string[] = [];

          rawLines.forEach(line => {
            const smartWrapped = smartWrapCodeLine(line, 74);
            wrappedEvLines.push(...smartWrapped);
          });

          const displayEvidence = wrappedEvLines.slice(0, 10);
          if (wrappedEvLines.length > 10) {
            displayEvidence.push('... (truncated for report length)');
          }

          const evBoxHeight = displayEvidence.length * 3.8 + 6;
          checkPageBreak(evBoxHeight + 8);

          doc.setFont('helvetica', 'bold');
          doc.setFontSize(7.5);
          doc.setTextColor(...TEXT_MUTED);
          doc.text('CODE EVIDENCE:', margin, y);
          y += 3.5;

          // Dark slate code block container
          doc.setFillColor(30, 41, 59); // Slate 800
          doc.setDrawColor(51, 65, 85);
          doc.setLineWidth(0.4);
          doc.roundedRect(margin, y, contentWidth, evBoxHeight, 2, 2, 'FD');

          doc.setFont('courier', 'normal');
          doc.setFontSize(7.5);
          doc.setTextColor(241, 245, 249);
          doc.text(displayEvidence, margin + 4, y + 4.8);

          y += evBoxHeight + 5;
        }

        // --- Recommendation Box ---
        if (splitRec.length > 0) {
          const recBoxHeight = splitRec.length * 4.0 + 6;
          checkPageBreak(recBoxHeight + 8);

          doc.setFont('helvetica', 'bold');
          doc.setFontSize(7.5);
          doc.setTextColor(5, 150, 105);
          doc.text('RECOMMENDATION:', margin, y);
          y += 3.5;

          doc.setFillColor(240, 253, 244);
          doc.setDrawColor(187, 247, 208);
          doc.setLineWidth(0.4);
          doc.roundedRect(margin, y, contentWidth, recBoxHeight, 2, 2, 'FD');

          // Green accent left bar inset cleanly inside rounded box
          doc.setFillColor(5, 150, 105);
          doc.roundedRect(margin + 0.8, y + 1.2, 1.8, recBoxHeight - 2.4, 0.8, 0.8, 'F');

          doc.setFont('helvetica', 'normal');
          doc.setFontSize(8.2);
          doc.setTextColor(6, 78, 59);
          doc.text(splitRec, margin + 5.5, y + 4.8);

          y += recBoxHeight + 5;
        }

        // --- Suggested PR Comment Box ---
        if (splitComment.length > 0) {
          const commentBoxHeight = splitComment.length * 4.0 + 6;
          checkPageBreak(commentBoxHeight + 8);

          doc.setFont('helvetica', 'bold');
          doc.setFontSize(7.5);
          doc.setTextColor(...PRIMARY);
          doc.text('SUGGESTED PR COMMENT:', margin, y);
          y += 3.5;

          doc.setFillColor(238, 242, 255);
          doc.setDrawColor(199, 210, 254);
          doc.setLineWidth(0.4);
          doc.roundedRect(margin, y, contentWidth, commentBoxHeight, 2, 2, 'FD');

          // Indigo accent left bar inset cleanly inside rounded box
          doc.setFillColor(...PRIMARY);
          doc.roundedRect(margin + 0.8, y + 1.2, 1.8, commentBoxHeight - 2.4, 0.8, 0.8, 'F');

          doc.setFont('helvetica', 'normal');
          doc.setFontSize(8.2);
          doc.setTextColor(49, 46, 129);
          doc.text(splitComment, margin + 5.5, y + 4.8);

          y += commentBoxHeight + 5;
        }

        // Separator between finding items
        y += 2;
        doc.setDrawColor(...BORDER_COLOR);
        doc.setLineWidth(0.3);
        doc.line(margin, y, pageWidth - margin, y);
        y += 8;
      });
    }

    // ── 7. Page Footers ───────────────────────────────────────────────────────
    const totalPages = (doc.internal as any).getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
      doc.setPage(i);

      doc.setDrawColor(...BORDER_COLOR);
      doc.setLineWidth(0.4);
      doc.line(margin, pageHeight - 10, pageWidth - margin, pageHeight - 10);

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(...TEXT_MUTED);
      doc.text('Confidential — ReviewAI Code Analysis & Intelligence Report', margin, pageHeight - 5);
      doc.text(`Page ${i} of ${totalPages}`, pageWidth - margin, pageHeight - 5, { align: 'right' });
    }

    const prId = review?.pr_number ? `PR_${review.pr_number}` : (review?.id ? review.id.substring(0, 8) : 'report');
    const filename = `Review_Result_${prId}.pdf`;
    doc.save(filename);
  }
}
