// Builds the `dade rbplus site` chart browser.
//
// The output is committed and shipped inside the package, since anyone who installs `dade` from
// PyPI has no Node and no way to build it. Bootstrap is compiled in rather than fetched, and every
// path the page asks for is relative, so a built site works from a subdirectory — which is what
// GitHub Pages serves a project site from.
const CssMinimizerPlugin = require('css-minimizer-webpack-plugin');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const TerserPlugin = require('terser-webpack-plugin');
const path = require('node:path');

module.exports = (_env, argv) => ({
  devtool: argv.mode === 'development' ? 'source-map' : false,
  entry: { site: './assets/site/index.tsx' },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: 'ts-loader',
        exclude: /node_modules/,
      },
      {
        test: /\.scss$/,
        use: [
          MiniCssExtractPlugin.loader,
          { loader: 'css-loader', options: { url: false } },
          {
            loader: 'sass-loader',
            // Bootstrap 5 still uses `@import` internally, which the modern Sass compiler warns
            // about at length on every build. The warnings belong to Bootstrap rather than to
            // anything written here, so they are silenced rather than left to bury real ones.
            options: {
              // `charset: false` stops Dart Sass prepending a UTF-8 byte-order mark to the output,
              // which a pre-commit hook strips and which would then drift the committed bundle from
              // a fresh build.
              sassOptions: {
                charset: false,
                quietDeps: true,
                silenceDeprecations: ['import', 'global-builtin'],
              },
            },
          },
        ],
      },
    ],
  },
  optimization: {
    minimizer: [
      // Bootstrap's licence notice stays inside the script rather than being drawn off into a file
      // of its own.
      new TerserPlugin({ extractComments: false }),
      // Bootstrap embeds percent-encoded SVG as data URIs, which the minifier's SVG pass tries to
      // parse as a document and warns about on every build. Nothing here is an SVG file, so the
      // pass has nothing to do and is turned off rather than left to complain.
      new CssMinimizerPlugin({
        minimizerOptions: { preset: ['default', { svgo: false }] },
      }),
    ],
  },
  output: {
    clean: true,
    filename: '[name].[contenthash:8].js',
    // Relative, so the page finds its own script wherever the site is served from.
    publicPath: '',
    path: path.resolve(__dirname, 'dade/rbplus/site'),
  },
  performance: { hints: false },
  plugins: [
    new MiniCssExtractPlugin({ filename: '[name].[contenthash:8].css' }),
    new HtmlWebpackPlugin({ minify: false, template: './assets/site/index.html' }),
  ],
  resolve: { extensions: ['.tsx', '.ts', '.js'] },
  target: 'browserslist:defaults',
});
