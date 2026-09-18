package assignment;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.UnsupportedEncodingException;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Map;

public class Server {
    public static void main(String[] args) throws IOException {
        int port = 8080;

        try (ServerSocket ss = new ServerSocket(port)) {
            System.out.println("Server listening on port : " + port);
            while (true) {
                try (Socket socket = ss.accept()) {
                    BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()));
                    BufferedWriter out = new BufferedWriter(new OutputStreamWriter(socket.getOutputStream()));
                    String requestLine;
                    while ((requestLine = in.readLine()) != null) {

                        System.out.println("Request: " + requestLine);
                        if (requestLine == null || requestLine.isEmpty())
                            continue;
                        String[] parts = requestLine.split(" ");
                        if (parts.length < 2)
                            continue;
                        String method = parts[0];
                        String rawPath = parts[1];
                        String pathOnly = rawPath.split("\\?")[0];

                        Map<String, String> queryParams = parseQueryParams(rawPath);
                        Map<String, String> headers = parseHeaders(in);

                        String responseBody = "";
                        String status = " 200 OK";
                        String contentType = "text/plain";

                        if (method.equals("POST")) {
                            int contentLength = headers.get("Content-Length") != null
                                    ? Integer.parseInt(headers.get("Content-Length"))
                                    : 0;
                            parseRequestBody(in, contentLength);
                            responseBody = "405 Method Not Allowed";
                            status = " 405 Method Not Allowed";
                        } else {
                            if (!headers.containsKey("Host")) {
                                responseBody = "400 Bad Request";
                                status = " 400 Bad Request";
                            }
                            switch (pathOnly) {
                                case "/add":
                                    if (queryParams.get("a") == null || queryParams.get("b") == null
                                            || !isNumeric(queryParams.get("a")) || !isNumeric(queryParams.get("b"))) {
                                        responseBody = "400 Bad Request";
                                        status = " 400 Bad Request";
                                        break;
                                    }
                                    int a1 = Integer.parseInt(queryParams.get("a"));
                                    int b1 = Integer.parseInt(queryParams.get("b"));

                                    responseBody = "" + (a1 + b1);
                                    contentType = "text/plain";
                                    break;

                                case "/sub":
                                    if (queryParams.get("a") == null || queryParams.get("b") == null
                                            || !isNumeric(queryParams.get("a")) || !isNumeric(queryParams.get("b"))) {
                                        responseBody = "400 Bad Request";
                                        status = " 400 Bad Request";
                                        break;
                                    }
                                    int a2 = Integer.parseInt(queryParams.get("a"));
                                    int b2 = Integer.parseInt(queryParams.get("b"));
                                    responseBody = "" + (a2 - b2);
                                    contentType = "text/plain";
                                    break;

                                case "/mul":
                                    if (queryParams.get("a") == null || queryParams.get("b") == null
                                            || !isNumeric(queryParams.get("a")) || !isNumeric(queryParams.get("b"))) {
                                        responseBody = "400 Bad Request";
                                        status = " 400 Bad Request";
                                        break;
                                    }
                                    int a3 = Integer.parseInt(queryParams.get("a"));
                                    int b3 = Integer.parseInt(queryParams.get("b"));
                                    responseBody = "" + (a3 * b3);
                                    contentType = "text/plain";
                                    break;

                                case "/div":
                                    if (queryParams.get("a") == null || queryParams.get("b") == null
                                            || !isNumeric(queryParams.get("a")) || !isNumeric(queryParams.get("b"))) {
                                        responseBody = "400 Bad Request";
                                        status = " 400 Bad Request";
                                        break;
                                    }
                                    int a4 = Integer.parseInt(queryParams.get("a"));
                                    int b4 = Integer.parseInt(queryParams.get("b"));
                                    if (b4 == 0) {
                                        responseBody = "400 Bad Request";
                                        status = " 400 Bad Request";
                                        break;
                                    }
                                    responseBody = "" + (a4 / b4);
                                    contentType = "text/plain";
                                    break;

                                default:
                                    responseBody = "404 Not Found";
                                    status = " 404 Not Found";
                                    break;
                            }
                        }

                        String httpResponse = "HTTP/1.1" + status + "\r\n" + "Content-Type: " + contentType + "\r\n"
                                + "Content-Length: " + responseBody.length() + "\r\n" + "\r\n" + responseBody;
                        out.write(httpResponse);
                        out.flush();
                    }
                }
            }
        }
    }

    public static boolean isNumeric(String a) {
        try {
            Double.parseDouble(a);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private static String parseRequestBody(BufferedReader in, int contentLength) throws IOException {
        char[] bodyChars = new char[contentLength];
        in.read(bodyChars, 0, contentLength);
        return new String(bodyChars);
    }

    public static Map<String, String> parseQueryParams(String rawPath) {
        try {
            Map<String, String> queryMap = new HashMap<>();
            if (rawPath.contains("?")) {
                String queryString = rawPath.split("\\?", 2)[1];
                for (String param : queryString.split("&")) {
                    String[] kv = param.split("=");
                    if (kv.length == 2) {
                        queryMap.put(URLDecoder.decode(kv[0], "UTF-8"),
                                URLDecoder.decode(kv[1], "UTF-8"));
                    }
                }
            }
            return queryMap;
        } catch (UnsupportedEncodingException ex) {
            ex.printStackTrace();
        }
        return new HashMap<>();
    }

    public static Map<String, String> parseHeaders(BufferedReader in) throws IOException {
        Map<String, String> headerMap = new HashMap<>();
        String line;

        while ((line = in.readLine()) != null && !line.isEmpty()) {
            int idx = line.indexOf(":");
            if (idx != -1) {
                String headerName = line.substring(0, idx).trim();
                String headerValue = line.substring(idx + 1).trim();
                headerMap.put(headerName, headerValue);
            }
        }

        return headerMap;
    }
}