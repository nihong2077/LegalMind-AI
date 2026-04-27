import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File;
    const token = request.headers.get('authorization') || '';
    
    const formDataToSend = new FormData();
    formDataToSend.append('file', file);
    
    const response = await fetch('http://127.0.0.1:8000/api/v1/agents/upload-document', {
      method: 'POST',
      headers: {
        'Authorization': token,
      },
      body: formDataToSend,
    });
    
    const result = await response.json();
    
    return NextResponse.json(result, {
      status: response.status,
      headers: {
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (error) {
    console.error('代理错误:', error);
    return NextResponse.json(
      { detail: '代理服务错误' },
      { status: 500 }
    );
  }
}
