import React from 'react';
import { useEvidenceList } from '../api/cases';

interface EvidenceListProps {
  caseId: string;
}

const formatBytes = (bytes: number, decimals = 2) => {
  if (!+bytes) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
};

export const EvidenceList: React.FC<EvidenceListProps> = ({ caseId }) => {
  const { data: evidenceList, isLoading, error } = useEvidenceList(caseId);

  if (isLoading) {
    return (
      <div className="bg-white p-6 rounded-lg shadow mt-6">
        <h2 className="text-xl font-bold mb-4 text-gray-800">Uploaded Evidence</h2>
        <div className="text-gray-500">Loading evidence...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white p-6 rounded-lg shadow mt-6">
        <h2 className="text-xl font-bold mb-4 text-gray-800">Uploaded Evidence</h2>
        <div className="text-red-500">Failed to load evidence. Please try again.</div>
      </div>
    );
  }

  if (!evidenceList || evidenceList.length === 0) {
    return (
      <div className="bg-white p-6 rounded-lg shadow mt-6">
        <h2 className="text-xl font-bold mb-4 text-gray-800">Uploaded Evidence</h2>
        <div className="text-gray-500 text-sm">No evidence has been uploaded for this case yet.</div>
      </div>
    );
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow mt-6">
      <h2 className="text-xl font-bold mb-4 text-gray-800">Uploaded Evidence</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left text-gray-500">
          <thead className="text-xs text-gray-700 uppercase bg-gray-50">
            <tr>
              <th scope="col" className="px-6 py-3">File Name</th>
              <th scope="col" className="px-6 py-3">Type</th>
              <th scope="col" className="px-6 py-3">Size</th>
              <th scope="col" className="px-6 py-3">Status</th>
              <th scope="col" className="px-6 py-3">Upload Date</th>
            </tr>
          </thead>
          <tbody>
            {evidenceList.map((item) => (
              <tr key={item.evidenceId} className="bg-white border-b hover:bg-gray-50">
                <td className="px-6 py-4 font-medium text-gray-900 break-all">{item.fileName}</td>
                <td className="px-6 py-4">{item.mimeType}</td>
                <td className="px-6 py-4">{formatBytes(item.fileSizeBytes)}</td>
                <td className="px-6 py-4">
                  <span
                    className={`px-2 py-1 rounded text-xs font-semibold ${
                      item.status === 'VERIFIED'
                        ? 'bg-green-100 text-green-800'
                        : item.status === 'REJECTED'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-yellow-100 text-yellow-800'
                    }`}
                  >
                    {item.status}
                  </span>
                </td>
                <td className="px-6 py-4">
                  {item.createdAt ? new Date(item.createdAt).toLocaleString() : 'N/A'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
